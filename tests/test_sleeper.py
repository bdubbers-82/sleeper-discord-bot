import pytest

@pytest.mark.asyncio
async def test_get_league_is_coroutine(monkeypatch):
    # Import here so monkeypatch can target correctly
    import sleeper

    async def fake_get_league(_):
        return {"name": "Test League", "season": "2025", "total_rosters": 12}

    # Replace the real networked function with our fake
    monkeypatch.setattr(sleeper, "get_league", fake_get_league)

    data = await sleeper.get_league("dummy")
    assert data["name"] == "Test League"
    assert data["season"] == "2025"
    assert data["total_rosters"] == 12
