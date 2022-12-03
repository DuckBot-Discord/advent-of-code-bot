CREATE TABLE linked_accounts(
    user_id BIGINT PRIMARY KEY,
    aoc_user_id BIGINT UNIQUE
)