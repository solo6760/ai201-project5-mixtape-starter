import pytest
from datetime import datetime, timedelta, timezone
from app import create_app, db
from models import User, Song, ListeningEvent, friendships
from services.feed_service import get_friends_listening_now


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
        user = User(username="me", email="me@example.com")
        friend1 = User(username="friend1", email="f1@example.com")
        friend2 = User(username="friend2", email="f2@example.com")
        db.session.add_all([user, friend1, friend2])
        db.session.flush()

        # Bidirectional friendship
        db.session.execute(friendships.insert().values(user_id=user.id, friend_id=friend1.id))
        db.session.execute(friendships.insert().values(user_id=friend1.id, friend_id=user.id))
        db.session.execute(friendships.insert().values(user_id=user.id, friend_id=friend2.id))
        db.session.execute(friendships.insert().values(user_id=friend2.id, friend_id=user.id))

        song = Song(title="Shared", artist="Artist", shared_by=user.id)
        db.session.add(song)
        db.session.commit()

        yield {"user": user, "friend1": friend1, "friend2": friend2, "song": song}


def test_friends_listening_now_threshold(app, seed_data):
    """Should only include friends active within the 30-minute threshold."""
    with app.app_context():
        now = datetime.now(timezone.utc)
        user_id = seed_data["user"].id
        song_id = seed_data["song"].id

        # Friend 1 listened 15 minutes ago (recent)
        event1 = ListeningEvent(
            user_id=seed_data["friend1"].id,
            song_id=song_id,
            listened_at=now - timedelta(minutes=15)
        )
        # Friend 2 listened 45 minutes ago (old)
        event2 = ListeningEvent(
            user_id=seed_data["friend2"].id,
            song_id=song_id,
            listened_at=now - timedelta(minutes=45)
        )
        db.session.add_all([event1, event2])
        db.session.commit()

        feed = get_friends_listening_now(user_id)
        
        # Only Friend 1 should show up
        assert len(feed) == 1
        assert feed[0]["friend"]["username"] == "friend1"
