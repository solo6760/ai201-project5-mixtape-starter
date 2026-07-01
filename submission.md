# Mixtape: Codebase Map & Submission Documentation

## 1. Codebase Map

### Core Architecture & App Structure

The Mixtape application follows a clean MVC/Service-oriented structure, decoupling the HTTP layer (routes) from the persistence and business logic layers (models and services).

```
ai201-project5-mixtape-starter/
├── app.py                      # Flask app factory, config, and SQLAlchemy setup
├── models.py                   # SQLAlchemy database models and relationships
├── routes/                     # Blueprint routers (handles requests and responses)
│   ├── songs.py                # Song details, rating, listening events, and search
│   ├── playlists.py            # Playlist creation, retrieval, and song management
│   ├── users.py                # User profiles, listening streaks, and notifications
│   └── feed.py                 # "Friends Listening Now" and general activity feeds
├── services/                   # Business logic layer (independent of HTTP)
│   ├── streak_service.py       # Manages user listening streaks based on consecutive days
│   ├── feed_service.py         # Aggregates active status/listening events of friends
│   ├── search_service.py       # Direct querying and searching of song titles/artists
│   ├── notification_service.py # Dispatches notifications and handles user ratings/playlist additions
│   └── playlist_service.py     # Retrieves and packages playlists and their ordered tracks
└── tests/                      # pytest test suites
```

---

### Main Files & Responsibilities

#### Initialization & Configuration
*   **[app.py]**: Contains the Flask application factory `create_app()`. It configures the database connection (defaulting to a local SQLite instance), registers the four blueprints (songs, playlists, users, feed) with their respective prefixes, and initializes the database schema (`db.create_all()`).

#### Persistence Layer (Database Schema)
*   **[models.py]**: Defines the SQLAlchemy schema. Key models include:
    *   `User`: Tracks username, email, listening streaks, and last active timestamps. Has relationships for activity and social connections.
    *   `Song`: Contains title, artist, genre, album, and original sharer references.
    *   `Playlist`: Represents playlist collections with collaborative flags.
    *   `Notification`: Handles system notification alerts (`notification_type`, message `body`, read status).
    *   `Rating` / `ListeningEvent`: Log rating scores (1–5) and listening action timestamps.
    *   *Association Tables*: `friendships` (symmetric many-to-many friendship mapping), `song_tags` (mapping tags to songs), and `playlist_entries` (adds order sequencing via a `position` column).

#### Presentation Layer (Flask Blueprints)
*   **[routes/songs.py](routes/songs.py)**: Exposes endpoints for searching songs, retrieving song details, rating a song, and recording a listening event. Delegates all calculations and DB writes to `search_service`, `notification_service`, and `streak_service`.
*   **[routes/playlists.py](routes/playlists.py)**: Maps paths for creating new playlists, fetching playlist tracks, and adding new songs to a playlist.
*   **[routes/users.py](routes/users.py)**: Maps endpoints for fetching user profiles, reading active listening streaks, querying user notifications, and marking notifications as read.
*   **[routes/feed.py](routes/feed.py)**: Exposes endpoints to check which friends are currently active (`/feed/<user_id>/listening-now`) and a chronological activity feed of friends' listening histories.

#### Business Logic Layer (Services)
*   **[services/streak_service.py](services/streak_service.py)**: Implements calendar-day streak increments, resets, and listening event logging.
*   **[services/feed_service.py](services/feed_service.py)**: Calculates active windows for friends and generates custom feeds.
*   **[services/search_service.py](services/search_service.py)**: Performs search lookups on songs.
*   **[services/notification_service.py](services/notification_service.py)**: Manages creation of user notification alerts, handles rating validation, and records playlist additions.
*   **[services/playlist_service.py](services/playlist_service.py)**: Queries and lists playlist entries in the correct position order.

---

### Data Flow: Adding a Song to a Playlist & Notifying the Sharer

Here is the trace of how adding a song to a playlist propagates through the app and triggers a notification:

1.  **Client POST Request**: A client calls `POST /playlists/<playlist_id>/songs` with a JSON body:
    ```json
    {
      "song_id": "<song_uuid>",
      "added_by": "<user_uuid>"
    }
    ```
2.  **Route Parsing**: In `routes/playlists.py`, the `add_song(playlist_id)` endpoint:
    *   Extracts `song_id` and `added_by` from the request JSON.
    *   Validates that both fields are provided (returns `400 Bad Request` if missing).
    *   Calls the service function `add_to_playlist(playlist_id, song_id, added_by)`.
3.  **Service Processing**: In `services/notification_service.py`, `add_to_playlist`:
    *   Looks up the target `Song`, adding `User`, and `Playlist` via `db.session.get`. If any are not found, raises a `ValueError` (which the route catches and translates to an HTTP error).
    *   Checks if the song is already in the playlist. If not, appends it to the playlist's `songs` relationship and commits the database session.
4.  **Notification Trigger**: If the user who added the song is **not** the person who originally shared the song (`song.shared_by != added_by_user_id`):
    *   It triggers `create_notification` to alert the original sharer.
5.  **Notification Creation**: In `services/notification_service.py`, `create_notification`:
    *   Creates a new `Notification` model instance:
        *   `user_id`: ID of the song's original sharer (`song.shared_by`).
        *   `notification_type`: `"song_added_to_playlist"`.
        *   `body`: `"{adder.username} added your song '{song.title}' to the playlist '{playlist.name}'."`
    *   Inserts the record into the database session and commits.
6.  **HTTP Response**: The route handler returns a JSON response `{"message": "Song added to playlist"}` with status code `201 Created`.

---

### Architectural Design Patterns

*   **Service Layer Separation**: The controllers (blueprints in `routes/`) act strictly as thin entry points. They validate request payloads, call services to perform business operations, catch service-level exceptions (converting them to appropriate HTTP error status codes like 404 or 400), and format JSON payloads. This makes testing business logic independent of Flask context easier.
*   **Relationship-Driven Aggregations**: The application makes heavy use of SQLAlchemy relationships (e.g., `user.friends`, `song.ratings`, `playlist.songs`).
*   **Explicit Order Tracking**: The `playlist_entries` join table holds an explicit `position` column rather than relying on insertion order, allowing playlists to support track sequencing.
*   **Subquery Pre-Loading**: Relationships like `Song.tags` are configured with `lazy="subquery"` to automatically load all tag records in a single query, optimizing tag reads and preventing N+1 queries.

---

## 2. Bug Reproduction & Root Cause Analysis

This section outlines the detailed Root Cause Analysis (RCA) for all five issues identified in the Mixtape application.

---

### Issue 1: My listening streak keeps resetting
*   **How you reproduced it**: 
    Under the test case `test_streak_increments_on_sunday` in [tests/test_streaks.py](tests/test_streaks.py), a user's `last_listened_at` is set to Saturday (e.g., `2024-06-15 12:00:00 UTC`), showing they listened yesterday. When calling `update_listening_streak(user, now)` with `now` set to Sunday (e.g., `2024-06-16 12:00:00 UTC`), the user's streak resets to `1` (observed behavior) instead of incrementing to `2` (expected).
*   **How you found the root cause**: 
    Traced from the `/listen` endpoint in [routes/songs.py](routes/songs.py) to `record_listening_event` in [services/streak_service.py](services/streak_service.py). Followed the logic into `update_listening_streak`. The moment of confidence was seeing `elif days_since_last == 1 and today.weekday() != 6:`. Knowing that Python's `datetime.weekday()` returns `6` on Sundays, this condition evaluates to `False` on Sundays, forcing the execution flow into the `else` block which resets the streak to `1`.
*   **The root cause**: 
    The conditional check `elif days_since_last == 1 and today.weekday() != 6:` explicitly prevented streaks from incrementing when the current check day (`today`) fell on a Sunday (where `weekday() == 6`). This caused any consecutive daily listen occurring on a Sunday to fail the condition and reset the user's streak back to 1.
*   **Your fix and side-effect check**: 
    Modified [services/streak_service.py](services/streak_service.py) to remove the `and today.weekday() != 6` check from the consecutive-day block. Afterward, ran `pytest` to verify the pre-existing streak tests passed. Added comprehensive weekend transition boundary tests in [tests/test_boundaries.py](tests/test_boundaries.py) to verify that streak increments work cleanly on Saturday-to-Sunday, Sunday-to-Monday, and same-day listens without side-effects (e.g. double incrementing).

---

### Issue 2: Friends Listening Now shows people from yesterday
*   **How you reproduced it**: 
    Created a test listening event for a friend dated 12 hours ago, then queried the feed. The friend appeared in the "Friends Listening Now" list despite not having listened to anything recently.
*   **How you found the root cause**: 
    Traced from the `/<user_id>/listening-now` endpoint in [routes/feed.py](routes/feed.py) to `get_friends_listening_now` in [services/feed_service.py](services/feed_service.py). Inspected the `cutoff` calculation `cutoff = datetime.now(timezone.utc) - RECENT_THRESHOLD`. The moment of confidence was seeing `RECENT_THRESHOLD = timedelta(hours=24)` at the top of the file. Comparing this with the design comments in `seed_data.py` (which expected events "within the past 30 minutes" to show up) confirmed the threshold range was misconfigured.
*   **The root cause**: 
    The global configuration constant `RECENT_THRESHOLD` was set to a 24-hour duration (`timedelta(hours=24)`) instead of a 30-minute duration (`timedelta(minutes=30)`). This overly broad window pulled in listening events from up to a day ago instead of limiting the feed to actively listening users.
*   **Your fix and side-effect check**: 
    Changed `RECENT_THRESHOLD` in [services/feed_service.py](services/feed_service.py) to `timedelta(minutes=30)`. Verified that this did not affect the activity feed logic (which uses record-count limits instead of time-window thresholds). Wrote boundary presence checks in [tests/test_feed.py](tests/test_feed.py) and [tests/test_boundaries.py](tests/test_boundaries.py) to ensure events at 29 minutes are included while events at 31 minutes are filtered out.

---

### Issue 3: The same song keeps showing up twice in search
*   **How you reproduced it**: 
    Created a song with three associated tags. Queried search matching the song title. The search output returned the song three separate times in the results list.
*   **How you found the root cause**: 
    Traced from the `/search` endpoint in [routes/songs.py](routes/songs.py) to `search_songs` in [services/search_service.py](services/search_service.py). Checked the database model relationships in [models.py](models.py). The moment of confidence was seeing the query `.outerjoin(song_tags, Song.id == song_tags.c.song_id)` in `search_songs` while `Song.tags` already used `lazy="subquery"`. The join created multiple result set rows for songs linked to multiple tags, producing duplication in SQL.
*   **The root cause**: 
    The search query performed an outer join to the `song_tags` junction table. Since tag associations are already pre-loaded separately via the `lazy="subquery"` relationship configuration on `Song`, the outer join was redundant. Because the query did not use `.distinct()` or grouping, it returned one `Song` instance per tag row in the database result set, generating duplicates for songs with multiple tags.
*   **Your fix and side-effect check**: 
    Removed the redundant `.outerjoin(song_tags, ...)` call in `search_songs()`, querying `Song` directly. Running the test suite shows all search tests (including `test_search_no_duplicates_multi_tag_song`) pass. Verified that the tags list associated with each song remains intact and populated correctly.

---

### Issue 4: Notification for playlist addition but not rating
*   **How you reproduced it**: 
    User B rated a song shared by User A. Verified the notification counts for User A. The rating record was successfully inserted in the database, but no notification entry was created.
*   **How you found the root cause**: 
    Traced from the `/<song_id>/rate` endpoint in [routes/songs.py](routes/songs.py) to `rate_song` in [services/notification_service.py](services/notification_service.py). Compared it with `add_to_playlist` in the same file. The moment of confidence was seeing that `add_to_playlist` had an explicit call to `create_notification` to alert the original sharer, while `rate_song` had no such call.
*   **The root cause**: 
    The `rate_song` service function in `services/notification_service.py` was missing the notification dispatch logic. It updated the `Rating` record in the database but did not invoke `create_notification` to notify the original sharer of the song.
*   **Your fix and side-effect check**: 
    Added the notification trigger in `rate_song()` using `create_notification(user_id=song.shared_by, notification_type="song_rated", ...)` if `song.shared_by != rater_id`. Created a new test suite [tests/test_notifications.py](tests/test_notifications.py) to check that rating a friend's song fires a notification but rating one's own song does not.

---

### Issue 5: The last song in a playlist never shows up
*   **How you reproduced it**: 
    Populated a playlist with 5 songs. Queried `/playlists/<id>/songs`. The endpoint returned only 4 songs, completely omitting the final track in the playlist sequence.
*   **How you found the root cause**: 
    Traced from `/playlists/<playlist_id>/songs` in [routes/playlists.py](routes/playlists.py) to `get_playlist_songs` in [services/playlist_service.py](services/playlist_service.py). The moment of confidence was inspecting the return statement: `return [song.to_dict() for song in songs[:-1]]`.
*   **The root cause**: 
    The `get_playlist_songs` function returned the list of song dicts using a slice slice `songs[:-1]`. This python slice drops the last element in the list, causing the final track of any playlist to be omitted from the output.
*   **Your fix and side-effect check**: 
    Removed the `[:-1]` slice from the return statement in `get_playlist_songs()` so that it returns `songs` fully. Verified playlist queries on empty playlists (0 tracks), single-song playlists (1 track), and multi-song playlists (5 tracks) in [tests/test_boundaries.py](tests/test_boundaries.py) to confirm it handles all list sizes correctly without index out of bounds.

---

## 3. AI Tool Usage Summary & Refinement

Throughout this phase, AI tools were leveraged to accelerate understanding and refine our hypotheses without executing arbitrary code changes:
1.  **Explaining Edge Cases**: Assisted in confirming python's `datetime.weekday()` behavior vs. `isoweekday()`.
2.  **Structural Comparisons**: Helped trace how similar interactions (e.g., playlist addition vs. rating) are structured in `services/notification_service.py` and flagged the structural omission.
3.  **SQLAlchemy Join Analysis**: Provided quick clarification on why duplicate results are fetched when query-joining table relationships in SQLite under ORMs.


