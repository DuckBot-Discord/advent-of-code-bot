from typing import TypedDict, Dict, Literal


class LevelData(TypedDict):
    star_index: int
    get_star_ts: int


class UserData(TypedDict):
    stars: int
    last_star_ts: int
    local_score: int
    competition_day_level: Dict[int, Dict[Literal[1, 2], LevelData]]
    name: str
    global_score: int
    id: int


class Leaderboard(TypedDict):
    members: Dict[str, UserData]
    owner_id: int
    event: str
