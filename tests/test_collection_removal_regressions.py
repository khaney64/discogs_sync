"""Removal regressions exercising real Discogs models with no network access."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from discogs_client.models import CollectionFolder, CollectionItemInstance

from discogs_sync import sync_collection as collection
from discogs_sync.exceptions import ConfirmationRequiredError
from discogs_sync.models import InputRecord, SearchResult


@pytest.fixture
def collection_client(monkeypatch):
    client = Mock()
    instances = []

    class Folder(CollectionFolder):
        @property
        def releases(self):
            return SimpleNamespace(page=lambda page: list(instances) if page == 1 else [])

    folders = {}
    for folder_id in (0, 7):
        folder = Folder(client, {
            "id": folder_id,
            "resource_url": f"https://api.discogs.com/users/test/collection/folders/{folder_id}",
        })
        folder.remove_release = Mock(wraps=folder.remove_release)
        folders[folder_id] = folder
    client.identity.return_value = SimpleNamespace(collection_folders=folders)

    def delete(url):
        instance_id = int(url.rsplit("/", 1)[1])
        instances[:] = [item for item in instances if item.instance_id != instance_id]

    client._delete.side_effect = delete
    monkeypatch.setattr(collection, "_api_call_with_retry", lambda call, limiter: call())

    def add(release_id, instance_id, master_id=None, artist="Pink Floyd", title="Animals"):
        instances.append(CollectionItemInstance(client, {
            "id": release_id, "instance_id": instance_id, "folder_id": 7,
            "basic_information": {
                "id": release_id, "master_id": master_id, "title": title,
                "artists": [{"name": artist}],
            },
        }))

    return SimpleNamespace(client=client, instances=instances, folders=folders, add=add)


def resolve_input(monkeypatch, kind):
    record = InputRecord(artist="Pink Floyd", album="Animals")
    result = SearchResult(
        input_record=record, release_id=495664,
        master_id=1000 if kind == "master" else None,
        artist="Pink Floyd", title="Animals", matched=True, score=1.0,
    )
    monkeypatch.setattr(collection, "search_release", lambda *args, **kwargs: result)
    monkeypatch.setattr(collection, "resolve_to_release_id", lambda *args: result.release_id)
    return record


@pytest.mark.parametrize("folder_id", [0, 7])
def test_single_removal_uses_instance_and_retains_other_copies(collection_client, folder_id):
    state = collection_client
    state.add(7122930, 11)
    state.add(7122930, 12)
    state.add(495664, 13)

    action = collection.remove_from_collection(
        state.client, release_id=7122930, folder_id=folder_id, confirm=True,
    )

    assert action.release_id == 7122930
    instance = state.folders[folder_id].remove_release.call_args.args[0]
    assert isinstance(instance, CollectionItemInstance)
    assert (instance.id, instance.instance_id, instance.folder_id) == (7122930, 11, folder_id)
    state.folders[folder_id].remove_release.assert_called_once_with(instance)
    state.client._delete.assert_called_once_with(
        f"https://api.discogs.com/users/test/collection/folders/{folder_id}/releases/7122930/instances/11",
    )
    assert [(item.id, item.instance_id) for item in state.instances] == [(7122930, 12), (495664, 13)]


def test_single_removal_preview_never_deletes(collection_client):
    state = collection_client
    state.add(7122930, 11)
    state.add(7122930, 12)

    with pytest.raises(ConfirmationRequiredError) as exc:
        collection.remove_from_collection(state.client, release_id=7122930)

    assert exc.value.preview["instance_id"] == 11
    assert exc.value.preview["copies_owned"] == 2
    state.client._delete.assert_not_called()
    assert len(state.instances) == 2


@pytest.mark.parametrize("kind", ["exact", "master", "fuzzy"])
@pytest.mark.parametrize("dry_run", [False, True])
def test_remove_extras_preserves_satisfying_pressings(monkeypatch, collection_client, kind, dry_run):
    state = collection_client
    record = resolve_input(monkeypatch, kind)
    kept_id = 495664 if kind == "exact" else 7122930
    # Master matches must work even when names do not pass the fuzzy check.
    title = "Different edition title" if kind == "master" else "Animals"
    state.add(kept_id, 11, master_id=1000, title=title)
    state.add(kept_id, 12, master_id=1000, title=title)
    kept = [(kept_id, 11), (kept_id, 12)]
    if kind != "exact":
        state.add(888, 14, master_id=1000, title=title)
        kept.append((888, 14))
    state.add(999, 21, master_id=2000, artist="Other artist", title="Other album")
    state.add(999, 22, master_id=2000, artist="Other artist", title="Other album")

    report = collection.sync_collection(
        state.client, [record], remove_extras=True, confirm_removals=True, dry_run=dry_run,
    )

    assert (report.skipped, report.added, report.removed, report.errors) == (1, 0, 2, 0)
    state.client._post.assert_not_called()
    if dry_run:
        state.client._delete.assert_not_called()
        assert len(state.instances) == len(kept) + 2
    else:
        assert [call.args[0] for call in state.client._delete.call_args_list] == [
            f"https://api.discogs.com/users/test/collection/folders/0/releases/999/instances/{instance_id}"
            for instance_id in (21, 22)
        ]
        assert [(item.id, item.instance_id) for item in state.instances] == kept


@pytest.mark.parametrize("kind", ["exact", "master", "fuzzy"])
def test_confirmation_counts_only_true_extras(monkeypatch, collection_client, kind):
    state = collection_client
    record = resolve_input(monkeypatch, kind)
    state.add(495664 if kind == "exact" else 7122930, 11, master_id=1000)
    state.add(999, 21, artist="Other artist", title="Other album")
    state.add(999, 22, artist="Other artist", title="Other album")

    with pytest.raises(ConfirmationRequiredError, match="would delete 2 item"):
        collection.sync_collection(state.client, [record], remove_extras=True)

    state.client._delete.assert_not_called()
    state.client._post.assert_not_called()


@pytest.mark.parametrize("kind", ["master", "fuzzy"])
def test_only_matching_pressing_needs_no_removal_confirmation(monkeypatch, collection_client, kind):
    state = collection_client
    record = resolve_input(monkeypatch, kind)
    state.add(7122930, 11, master_id=1000)

    report = collection.sync_collection(state.client, [record], remove_extras=True)

    assert (report.skipped, report.removed, report.errors) == (1, 0, 0)
    state.client._delete.assert_not_called()
    state.client._post.assert_not_called()
