import pytest
from datetime import datetime, timedelta, timezone
from app import create_app, db
from models import User, Song, ListeningEvent, Playlist, playlist_entries, friendships
from services.streak_service import update_listening_streak
from services.feed_service import get_friends_listening_now
from services.playlist_service import get_playlist_songs


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


# --- ISSUE 1: STREAK BOUNDARY TESTS ---

def test_streak_boundary_consecutive_days(app):
    """Test consecutive streak increments across all day transitions, including weekend boundaries."""
    with app.app_context():
        u = User(username="streak_user", email="streak@example.com")
        db.session.add(u)
        db.session.commit()

        # Day 0: Monday
        day0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        update_listening_streak(u, day0)
        assert u.listening_streak == 1

        # Day 1: Tuesday (consecutive)
        day1 = datetime(2026, 6, 2, 12, 0, 0, tzinfo=timezone.utc)
        update_listening_streak(u, day1)
        assert u.listening_streak == 2

        # Day 5: Saturday (mocking state)
        u.last_listened_at = datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc)
        u.listening_streak = 5
        db.session.commit()

        # Day 6: Sunday (consecutive Saturday -> Sunday) -> Should increment to 6
        day6 = datetime(2026, 6, 7, 12, 0, 0, tzinfo=timezone.utc)
        update_listening_streak(u, day6)
        assert u.listening_streak == 6

        # Day 7: Monday (consecutive Sunday -> Monday) -> Should increment to 7
        day7 = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)
        update_listening_streak(u, day7)
        assert u.listening_streak == 7


def test_streak_boundary_same_day_vs_skipped(app):
    """Test same-day listen (no change) and skipped-day listen (reset)."""
    with app.app_context():
        u = User(username="streak_user", email="streak@example.com")
        db.session.add(u)
        db.session.commit()

        # Initial listen
        t0 = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
        update_listening_streak(u, t0)
        assert u.listening_streak == 1

        # Same-day subsequent listen (no change)
        t0_sub = datetime(2026, 6, 1, 21, 0, 0, tzinfo=timezone.utc)
        update_listening_streak(u, t0_sub)
        assert u.listening_streak == 1

        # Skip Tuesday, listen on Wednesday -> Should reset to 1
        t2 = datetime(2026, 6, 3, 12, 0, 0, tzinfo=timezone.utc)
        update_listening_streak(u, t2)
        assert u.listening_streak == 1


# --- ISSUE 2: FEED PRESENCE RANGE BOUNDARY TESTS ---

def test_feed_presence_threshold_boundary(app):
    """Test feed presence for events strictly within 30 minutes vs outside."""
    with app.app_context():
        me = User(username="me", email="me@example.com")
        friend = User(username="friend", email="friend@example.com")
        db.session.add_all([me, friend])
        db.session.flush()

        db.session.execute(friendships.insert().values(user_id=me.id, friend_id=friend.id))
        db.session.execute(friendships.insert().values(user_id=friend.id, friend_id=me.id))

        song = Song(title="Test Song", artist="Artist", shared_by=me.id)
        db.session.add(song)
        db.session.commit()

        now = datetime.now(timezone.utc)

        # 1. 29 minutes ago (Within boundary) -> Should appear
        event_inside = ListeningEvent(user_id=friend.id, song_id=song.id, listened_at=now - timedelta(minutes=29))
        db.session.add(event_inside)
        db.session.commit()

        feed = get_friends_listening_now(me.id)
        assert len(feed) == 1

        # Clean event
        db.session.delete(event_inside)
        db.session.commit()

        # 2. 31 minutes ago (Outside boundary) -> Should NOT appear
        event_outside = ListeningEvent(user_id=friend.id, song_id=song.id, listened_at=now - timedelta(minutes=31))
        db.session.add(event_outside)
        db.session.commit()

        feed = get_friends_listening_now(me.id)
        assert len(feed) == 0


# --- ISSUE 5: PLAYLIST SIZE BOUNDARY TESTS ---

def test_playlist_size_boundaries(app):
    """Test playlist retrieval for size 0, 1, and 5 tracks."""
    with app.app_context():
        user = User(username="dj", email="dj@example.com")
        db.session.add(user)
        db.session.flush()

        # Playlist 1: Empty
        playlist_empty = Playlist(name="Empty", created_by=user.id)
        db.session.add(playlist_empty)
        db.session.flush()

        # Playlist 2: Single song
        playlist_single = Playlist(name="Single", created_by=user.id)
        db.session.add(playlist_single)
        db.session.flush()

        # Playlist 3: Multi (5 songs)
        playlist_multi = Playlist(name="Multi", created_by=user.id)
        db.session.add(playlist_multi)
        db.session.flush()

        songs = [Song(title=f"Track {i}", artist="Artist", shared_by=user.id) for i in range(1, 6)]
        db.session.add_all(songs)
        db.session.flush()

        # Populate Single
        db.session.execute(
            playlist_entries.insert().values(
                playlist_id=playlist_single.id, song_id=songs[0].id, position=1, added_by=user.id
            )
        )

        # Populate Multi
        for i, song in enumerate(songs):
            db.session.execute(
                playlist_entries.insert().values(
                    playlist_id=playlist_multi.id, song_id=song.id, position=i + 1, added_by=user.id
                )
            )
        db.session.commit()

        # Verify Empty Playlist (Boundary = 0)
        assert len(get_playlist_songs(playlist_empty.id)) == 0

        # Verify Single Song Playlist (Boundary = 1)
        single_songs = get_playlist_songs(playlist_single.id)
        assert len(single_songs) == 1
        assert single_songs[0]["title"] == "Track 1"

        # Verify Multi Song Playlist (Boundary = 5)
        multi_songs = get_playlist_songs(playlist_multi.id)
        assert len(multi_songs) == 5
        assert [s["title"] for s in multi_songs] == ["Track 1", "Track 2", "Track 3", "Track 4", "Track 5"]
