## AI Usage Section

During this project, AI was utilized as a collaborative pair programming partner to guide codebase orientation and refine root cause analyses:

1.  **Codebase Orientation & Structure**: 
    *   We asked the AI to explain specific structures in the models (such as many-to-many relationships and order-based join tables) and trace dependencies between routes and services.
    *   The AI clarified how blueprints under `routes/` delegate operations to `services/`, and how SQLAlchemy relationship mapping handles entity aggregation.
2.  **Debugging & Root Cause Analysis (RCA)**:
    *   We asked the AI to clarify python's `datetime.weekday()` returns, analyze duplication results when query-joining table relationships in SQLite under ORMs, and walk through playlist list slicing (`songs[:-1]`).
    *   The AI immediately identified that `today.weekday()` returns 6 on Sundays (causing Sunday check reset) and verified the exclusive list slicing behavior of `[:-1]` in `get_playlist_songs`.
3.  **Verification & Gap Analysis**:
    *   The AI initially attempted to create a local virtual environment directly, but the workspace's NTFS file system mount created path format mismatches (`Exec format error`) on the Linux OS. We had to diagnose that the `.venv` directory contained Windows binaries and manually adapt by using the user's active terminal virtual environment setup.
    *   The AI's initial code search missed that the rating function (`rate_song`) had no notification trigger logic whatsoever. We had to inspect `services/notification_service.py` directly and design the trigger condition (`if song.shared_by != user_id`) and text content ourselves.

---

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

*   The controllers (blueprints in `routes/`) act strictly as thin entry points. They validate request payloads, call services to perform business operations, catch service-level exceptions (converting them to appropriate HTTP error status codes like 404 or 400), and format JSON payloads. This makes testing business logic independent of Flask context easier.
*   The application makes heavy use of SQLAlchemy relationships (e.g., `user.friends`, `song.ratings`, `playlist.songs`).
*   The `playlist_entries` join table holds an explicit `position` column rather than relying on insertion order, allowing playlists to support track sequencing.
*   Relationships like `Song.tags` are configured with `lazy="subquery"` to automatically load all tag records in a single query, optimizing tag reads and preventing N+1 queries.

---

## 2. Bug Reproduction & Root Cause Analysis

This section summarizes the reproduction steps, root causes, and fixes for the five core issues.

---

### Issue 1: My listening streak keeps resetting
* Ran `test_streak_increments_on_sunday` in [test_streaks.py](tests/test_streaks.py); consecutive Sunday listens reset streaks to 1 instead of incrementing.
* In [streak_service.py](services/streak_service.py), `elif days_since_last == 1 and today.weekday() != 6:` explicitly blocked streak increments on Sundays (`weekday() == 6`).
* Removed the `and today.weekday() != 6` check and added weekend transition boundary tests in [test_boundaries.py](tests/test_boundaries.py).

---

### Issue 2: Friends Listening Now shows people from yesterday
* Seeded a friend's listening event 12 hours ago and verified they incorrectly appeared in the active feed.
* In [feed_service.py](services/feed_service.py), `RECENT_THRESHOLD` was set to `timedelta(hours=24)` instead of the design-specified `timedelta(minutes=30)`.
* Changed `RECENT_THRESHOLD` to `timedelta(minutes=30)` and added presence boundary checks in [test_feed.py](tests/test_feed.py).

---

### Issue 3: The same song keeps showing up twice in search
* Searched for a song associated with multiple tags; it returned duplicate results for each tag.
* The query in [search_service.py](services/search_service.py) performed a redundant `.outerjoin(song_tags, ...)` without grouping or using `.distinct()`.
* Removed the redundant join, since tags are already pre-loaded separately via subqueries in [models.py](models.py).

---

### Issue 4: Notification for playlist addition but not rating
* Rated a friend's shared song and observed that a notification was never dispatched to the owner.
* The `rate_song` function in [notification_service.py](services/notification_service.py) was missing a call to `create_notification`.
* Added a call to `create_notification` inside `rate_song` (only when the rater is not the owner) and verified via [test_notifications.py](tests/test_notifications.py).

---

### Issue 5: The last song in a playlist never shows up
* Added 5 songs to a playlist and fetched it; only the first 4 songs were returned.
* In [playlist_service.py](services/playlist_service.py), `get_playlist_songs` returned a sliced list `songs[:-1]`, which dropped the final track.
* **Fix**: Removed the `[:-1]` slice from the return statement.

---

## 3. AI Tool Usage Summary & Refinement

Throughout this phase, AI tools were leveraged to accelerate understanding and refine our hypotheses without executing arbitrary code changes:
1. Assisted in confirming python's `datetime.weekday()` behavior vs. `isoweekday()`.
2. Helped trace how similar interactions (e.g., playlist addition vs. rating) are structured in `services/notification_service.py` and flagged the structural omission.
3. Provided quick clarification on why duplicate results are fetched when query-joining table relationships in SQLite under ORMs.


