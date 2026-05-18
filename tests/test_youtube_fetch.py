from app.sources.youtube_fetch import extract_video_id, parse_youtube_lines


def test_parse_youtube_lines():
    text = "https://youtu.be/abcdefghijk\n# skip\n"
    assert parse_youtube_lines(text) == ["https://youtu.be/abcdefghijk"]


def test_extract_video_id_watch():
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert extract_video_id(url) == "dQw4w9WgXcQ"


def test_extract_video_id_shorts():
    url = "https://www.youtube.com/shorts/dQw4w9WgXcQ"
    assert extract_video_id(url) == "dQw4w9WgXcQ"


def test_extract_video_id_youtu_be():
    url = "https://youtu.be/dQw4w9WgXcQ"
    assert extract_video_id(url) == "dQw4w9WgXcQ"
