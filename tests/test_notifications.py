import pytest
from app import create_app, db
from models import User, Song, Rating, Notification
from services.notification_service import rate_song, get_notifications


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def seed_data(app):
    with app.app_context():
        user_a = User(username="user_a", email="a@example.com")
        user_b = User(username="user_b", email="b@example.com")
        db.session.add_all([user_a, user_b])
        db.session.flush()

        song = Song(title="Test Song", artist="Test Artist", shared_by=user_a.id)
        db.session.add(song)
        db.session.commit()

        yield {"user_a": user_a, "user_b": user_b, "song": song}


def test_rating_by_friend_notifies_sharer(app, seed_data):
    """Rating a song shared by a friend should send a notification to the sharer."""
    with app.app_context():
        user_a_id = seed_data["user_a"].id
        user_b_id = seed_data["user_b"].id
        song_id = seed_data["song"].id

        # User B rates User A's song
        rate_song(user_b_id, song_id, 5)

        # User A should have 1 notification
        notifs = get_notifications(user_a_id)
        assert len(notifs) == 1
        assert notifs[0]["type"] == "song_rated"
        assert "user_b rated your song" in notifs[0]["body"]

        # User B should have 0 notifications
        assert len(get_notifications(user_b_id)) == 0


def test_rating_own_song_does_not_notify(app, seed_data):
    """Rating one's own song should not trigger a notification."""
    with app.app_context():
        user_a_id = seed_data["user_a"].id
        song_id = seed_data["song"].id

        # User A rates their own song
        rate_song(user_a_id, song_id, 4)

        # User A should not get a notification for rating their own song
        assert len(get_notifications(user_a_id)) == 0
