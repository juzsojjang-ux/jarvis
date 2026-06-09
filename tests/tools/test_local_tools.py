import asyncio

from jarvis.tools.builtin.local_tools import calc, make_remember_tool


def test_calc_adds_integers():
    assert asyncio.run(calc.call({"expression": "3 + 5"})) == "3 + 5 = 8"


def test_calc_handles_parens_and_precedence():
    assert asyncio.run(calc.call({"expression": "12 * (4 - 1)"})) == "12 * (4 - 1) = 36"


def test_calc_rejects_non_arithmetic_safely():
    out = asyncio.run(calc.call({"expression": "__import__('os').system('ls')"}))
    assert "계산할 수 없" in out  # no eval, no exception leaking — clean Korean error


def test_remember_tool_stores_via_memory_and_confirms():
    class FakeMemory:
        def __init__(self):
            self.notes = []

        def remember(self, note):
            self.notes.append(note)

    mem = FakeMemory()
    tool = make_remember_tool(mem)
    assert tool.name == "remember"
    out = asyncio.run(tool.call({"note": "내일 3시 회의"}))
    assert mem.notes == ["내일 3시 회의"]
    assert "내일 3시 회의" in out
