from incraw.resolve import choose, fold, rank

R_JAN_ALLEGRO = {"slug": "jan-k-1", "text": "Jan Kowalski\n• 2nd\nSenior Engineer at Allegro\nPoznań"}
R_JAN_OTHER = {"slug": "jan-k-2", "text": "Jan Kowalski • 3rd+\nAccountant at PKO\nKraków"}
R_JANUSZ = {"slug": "janusz-k", "text": "Janusz Kowalczyk\n• 3rd+\nDriver"}
R_MEMBER = {"slug": "x", "text": "LinkedIn Member\nEngineer"}


def test_fold_handles_polish():
    assert fold("Łukasz Żółć") == "lukasz zolc"


def test_company_breaks_tie():
    cands = rank("Jan Kowalski", "Allegro", [R_JAN_OTHER, R_JAN_ALLEGRO, R_JANUSZ])
    assert cands[0].slug == "jan-k-1"
    assert choose(cands).slug == "jan-k-1"


def test_same_name_without_company_is_ambiguous():
    cands = rank("Jan Kowalski", "", [R_JAN_ALLEGRO, R_JAN_OTHER])
    assert choose(cands) is None


def test_single_exact_match_is_picked():
    cands = rank("jan kowalski", "", [R_JAN_ALLEGRO, R_JANUSZ, R_MEMBER])
    assert [c.slug for c in cands] == ["jan-k-1", "janusz-k"]
    assert choose(cands).slug == "jan-k-1"
    assert cands[0].name == "Jan Kowalski"
    assert "Allegro" in cands[0].subtitle
