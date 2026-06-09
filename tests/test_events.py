from jarvis.core.events import SpeechChunk, State, Transcript


def test_state_members():
    assert [s.name for s in State] == [
        "IDLE", "CAPTURING", "TRANSCRIBING", "THINKING", "SPEAKING"
    ]


def test_event_dataclasses_are_frozen():
    t = Transcript(text="안녕")
    c = SpeechChunk(text="네")
    assert t.text == "안녕"
    assert c.text == "네"
    try:
        t.text = "x"
        raised = False
    except Exception:
        raised = True
    assert raised
