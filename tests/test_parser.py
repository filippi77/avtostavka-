from suitbot.parser import bet_wins, parse_game, parse_game_number, parse_pick

FINAL = "#N207. 7(J♦️ 7♣️) - ✅9(2♦️ 7♥️) #T16 🔵 #R"


def test_parse_final_post():
    r = parse_game(FINAL)
    assert r.number == 207
    assert (r.player_points, r.banker_points) == (7, 9)
    assert r.player_cards == (("J", "♦"), ("7", "♣"))
    assert r.banker_cards == (("2", "♦"), ("7", "♥"))
    assert r.player_suits == {"♦", "♣"}
    assert r.winner == "B"
    assert r.finished


def test_in_progress_post_is_not_finished():
    r = parse_game("⏰#N208. ▶ 5(10♠️ 5♥️) - 3(A♣️ 2♦️)")
    assert r.number == 208
    assert r.player_cards == (("10", "♠"), ("5", "♥"))
    assert not r.finished


def test_player_win_with_three_cards():
    r = parse_game("#N12. ✅8(3♠️ 2♥️ 3♣️) - 6(K♦️ 6♦️)")
    assert r.winner == "P"
    assert r.player_suits == {"♠", "♥", "♣"}


def test_tie():
    assert parse_game("#N13. 9(9♠️ K♥️) - 9(4♣️ 5♦️)").winner == "T"


def test_unrelated_text():
    assert parse_game("Черв догон ставь") is None
    assert parse_game_number("Черв догон ставь") is None
    assert parse_game_number("⏰#N209. ▶") == 209


def test_parse_pick():
    assert parse_pick("♥️") == ("suit", "♥")
    assert parse_pick("Буби") == ("suit", "♦")
    assert parse_pick("пики") == ("suit", "♠")
    assert parse_pick("игрок") == ("side", "P")
    assert parse_pick("банкир") == ("side", "B")
    assert parse_pick("ничья") == ("side", "T")
    assert parse_pick("xyz") is None


def test_bet_wins():
    r = parse_game(FINAL)
    assert bet_wins("suit", "♦", r)
    assert bet_wins("suit", "♣", r)
    assert not bet_wins("suit", "♥", r)  # черва только у банкира
    assert bet_wins("side", "B", r)
    assert not bet_wins("side", "P", r)


def test_result_sources_accept_username():
    from suitbot.config import _chats
    assert _chats("@Statistika_Baccara, -100123") == {"statistika_baccara", -100123}


def test_hourglass_post_from_channel():
    r = parse_game("⏳ #N272. ▶️ 2(7♣️ 5♥️) - 2(6♠️ 6♦️)")
    assert r.number == 272 and not r.finished
    assert r.player_cards == (("7", "♣"), ("5", "♥"))


def test_cards_bet():
    r = parse_game("#N7. 8(5♦ 3♦) - 9(Q♠ 4♥ 5♣)")
    assert bet_wins("cards", "23", r) and not bet_wins("cards", "22", r)
    r = parse_game("#N8. 8(5♦ 3♦) - 7(Q♠ 7♥)")
    assert bet_wins("cards", "22", r) and not bet_wins("cards", "23", r)
