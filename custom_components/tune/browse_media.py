"""Media browser support for Tune Music Server."""
from __future__ import annotations

from homeassistant.components.media_player import BrowseMedia, MediaClass, MediaType

from .coordinator import TuneCoordinator

LIBRARY_ROOT = "tune_library"


async def async_browse_media(
    coordinator: TuneCoordinator,
    zone_id: int,
    media_content_type: MediaType | str | None = None,
    media_content_id: str | None = None,
) -> BrowseMedia:
    """Browse Tune library."""
    if media_content_type is None or media_content_id is None:
        return _root_menu(coordinator)

    if media_content_id == "albums":
        return await _browse_albums(coordinator)
    if media_content_id == "artists":
        return await _browse_artists(coordinator)
    if media_content_id == "playlists":
        return await _browse_playlists(coordinator)
    if media_content_id == "genres":
        return await _browse_genres(coordinator)
    if media_content_id == "radios":
        return await _browse_radios(coordinator)

    if media_content_type == MediaType.ARTIST:
        return await _browse_artist_albums(coordinator, media_content_id)
    if media_content_type == MediaType.ALBUM:
        return await _browse_album_tracks(coordinator, media_content_id)
    if media_content_type == MediaType.PLAYLIST:
        return await _browse_playlist_tracks(coordinator, media_content_id)
    if media_content_type == "genre":
        return await _browse_genre_albums(coordinator, media_content_id)

    return _root_menu(coordinator)


def _root_menu(coordinator: TuneCoordinator) -> BrowseMedia:
    """Return the top-level library menu."""
    children = [
        BrowseMedia(
            title="Albums",
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.ALBUM,
            media_content_id="albums",
            can_play=False,
            can_expand=True,
            thumbnail=None,
        ),
        BrowseMedia(
            title="Artists",
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.ARTIST,
            media_content_id="artists",
            can_play=False,
            can_expand=True,
            thumbnail=None,
        ),
        BrowseMedia(
            title="Playlists",
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.PLAYLIST,
            media_content_id="playlists",
            can_play=False,
            can_expand=True,
            thumbnail=None,
        ),
        BrowseMedia(
            title="Genres",
            media_class=MediaClass.DIRECTORY,
            media_content_type="genre",
            media_content_id="genres",
            can_play=False,
            can_expand=True,
            thumbnail=None,
        ),
        BrowseMedia(
            title="Radio Stations",
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.CHANNEL,
            media_content_id="radios",
            can_play=False,
            can_expand=True,
            thumbnail=None,
        ),
    ]
    return BrowseMedia(
        title="Tune Library",
        media_class=MediaClass.DIRECTORY,
        media_content_type="library",
        media_content_id=LIBRARY_ROOT,
        can_play=False,
        can_expand=True,
        children=children,
    )


def _artwork_url(coordinator: TuneCoordinator, cover: str | None) -> str | None:
    if not cover:
        return None
    return f"{coordinator.base_url}/library/artwork/{cover}"


async def _browse_albums(coordinator: TuneCoordinator) -> BrowseMedia:
    data = await coordinator.api_get("/library/albums?limit=200")
    items = data if isinstance(data, list) else data.get("albums", [])
    children = [
        BrowseMedia(
            title=a.get("title", "?"),
            media_class=MediaClass.ALBUM,
            media_content_type=MediaType.ALBUM,
            media_content_id=str(a["id"]),
            can_play=True,
            can_expand=True,
            thumbnail=_artwork_url(coordinator, a.get("cover_hash")),
        )
        for a in items
        if a.get("id")
    ]
    return BrowseMedia(
        title="Albums",
        media_class=MediaClass.DIRECTORY,
        media_content_type=MediaType.ALBUM,
        media_content_id="albums",
        can_play=False,
        can_expand=True,
        children=children,
    )


async def _browse_artists(coordinator: TuneCoordinator) -> BrowseMedia:
    data = await coordinator.api_get("/library/artists?limit=200")
    items = data if isinstance(data, list) else data.get("artists", [])
    children = [
        BrowseMedia(
            title=a.get("name", "?"),
            media_class=MediaClass.ARTIST,
            media_content_type=MediaType.ARTIST,
            media_content_id=str(a["id"]),
            can_play=False,
            can_expand=True,
            thumbnail=None,
        )
        for a in items
        if a.get("id")
    ]
    return BrowseMedia(
        title="Artists",
        media_class=MediaClass.DIRECTORY,
        media_content_type=MediaType.ARTIST,
        media_content_id="artists",
        can_play=False,
        can_expand=True,
        children=children,
    )


async def _browse_artist_albums(
    coordinator: TuneCoordinator, artist_id: str
) -> BrowseMedia:
    data = await coordinator.api_get(f"/library/artists/{artist_id}/albums")
    items = data if isinstance(data, list) else data.get("albums", [])
    children = [
        BrowseMedia(
            title=a.get("title", "?"),
            media_class=MediaClass.ALBUM,
            media_content_type=MediaType.ALBUM,
            media_content_id=str(a["id"]),
            can_play=True,
            can_expand=True,
            thumbnail=_artwork_url(coordinator, a.get("cover_hash")),
        )
        for a in items
        if a.get("id")
    ]
    artist_info = await coordinator.api_get(f"/library/artists/{artist_id}")
    name = artist_info.get("name", "Artist") if isinstance(artist_info, dict) else "Artist"
    return BrowseMedia(
        title=name,
        media_class=MediaClass.ARTIST,
        media_content_type=MediaType.ARTIST,
        media_content_id=artist_id,
        can_play=False,
        can_expand=True,
        children=children,
    )


async def _browse_album_tracks(
    coordinator: TuneCoordinator, album_id: str
) -> BrowseMedia:
    data = await coordinator.api_get(f"/library/albums/{album_id}/tracks")
    items = data if isinstance(data, list) else data.get("tracks", [])
    children = [
        BrowseMedia(
            title=f"{t.get('track_number', '')}. {t.get('title', '?')}",
            media_class=MediaClass.TRACK,
            media_content_type=MediaType.TRACK,
            media_content_id=str(t["id"]),
            can_play=True,
            can_expand=False,
            thumbnail=None,
        )
        for t in items
        if t.get("id")
    ]
    album_info = await coordinator.api_get(f"/library/albums/{album_id}")
    title = album_info.get("title", "Album") if isinstance(album_info, dict) else "Album"
    return BrowseMedia(
        title=title,
        media_class=MediaClass.ALBUM,
        media_content_type=MediaType.ALBUM,
        media_content_id=album_id,
        can_play=True,
        can_expand=True,
        children=children,
    )


async def _browse_playlists(coordinator: TuneCoordinator) -> BrowseMedia:
    data = await coordinator.api_get("/playlists")
    items = data if isinstance(data, list) else data.get("playlists", [])
    children = [
        BrowseMedia(
            title=p.get("name", "?"),
            media_class=MediaClass.PLAYLIST,
            media_content_type=MediaType.PLAYLIST,
            media_content_id=str(p["id"]),
            can_play=True,
            can_expand=True,
            thumbnail=None,
        )
        for p in items
        if p.get("id")
    ]
    return BrowseMedia(
        title="Playlists",
        media_class=MediaClass.DIRECTORY,
        media_content_type=MediaType.PLAYLIST,
        media_content_id="playlists",
        can_play=False,
        can_expand=True,
        children=children,
    )


async def _browse_playlist_tracks(
    coordinator: TuneCoordinator, playlist_id: str
) -> BrowseMedia:
    data = await coordinator.api_get(f"/playlists/{playlist_id}/tracks")
    items = data if isinstance(data, list) else data.get("tracks", [])
    children = [
        BrowseMedia(
            title=t.get("title", "?"),
            media_class=MediaClass.TRACK,
            media_content_type=MediaType.TRACK,
            media_content_id=str(t["id"]),
            can_play=True,
            can_expand=False,
            thumbnail=None,
        )
        for t in items
        if t.get("id")
    ]
    return BrowseMedia(
        title="Playlist",
        media_class=MediaClass.PLAYLIST,
        media_content_type=MediaType.PLAYLIST,
        media_content_id=playlist_id,
        can_play=True,
        can_expand=True,
        children=children,
    )


async def _browse_genres(coordinator: TuneCoordinator) -> BrowseMedia:
    data = await coordinator.api_get("/library/genres")
    items = data if isinstance(data, list) else data.get("genres", [])
    children = [
        BrowseMedia(
            title=g.get("name", g) if isinstance(g, dict) else str(g),
            media_class=MediaClass.GENRE,
            media_content_type="genre",
            media_content_id=g.get("name", g) if isinstance(g, dict) else str(g),
            can_play=False,
            can_expand=True,
            thumbnail=None,
        )
        for g in items
    ]
    return BrowseMedia(
        title="Genres",
        media_class=MediaClass.DIRECTORY,
        media_content_type="genre",
        media_content_id="genres",
        can_play=False,
        can_expand=True,
        children=children,
    )


async def _browse_genre_albums(
    coordinator: TuneCoordinator, genre_name: str
) -> BrowseMedia:
    from urllib.parse import quote
    data = await coordinator.api_get(f"/library/genres/{quote(genre_name)}/albums")
    items = data if isinstance(data, list) else data.get("albums", [])
    children = [
        BrowseMedia(
            title=a.get("title", "?"),
            media_class=MediaClass.ALBUM,
            media_content_type=MediaType.ALBUM,
            media_content_id=str(a["id"]),
            can_play=True,
            can_expand=True,
            thumbnail=_artwork_url(coordinator, a.get("cover_hash")),
        )
        for a in items
        if a.get("id")
    ]
    return BrowseMedia(
        title=genre_name,
        media_class=MediaClass.GENRE,
        media_content_type="genre",
        media_content_id=genre_name,
        can_play=False,
        can_expand=True,
        children=children,
    )


async def _browse_radios(coordinator: TuneCoordinator) -> BrowseMedia:
    data = await coordinator.api_get("/radios")
    items = data if isinstance(data, list) else data.get("radios", [])
    children = [
        BrowseMedia(
            title=r.get("name", "?"),
            media_class=MediaClass.CHANNEL,
            media_content_type=MediaType.CHANNEL,
            media_content_id=str(r["id"]),
            can_play=True,
            can_expand=False,
            thumbnail=r.get("logo_url"),
        )
        for r in items
        if r.get("id")
    ]
    return BrowseMedia(
        title="Radio Stations",
        media_class=MediaClass.DIRECTORY,
        media_content_type=MediaType.CHANNEL,
        media_content_id="radios",
        can_play=False,
        can_expand=True,
        children=children,
    )
