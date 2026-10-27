from incraw.inputs import parse_line, parse_text, slug_from_url


def test_slug_variants():
    assert slug_from_url("https://www.linkedin.com/in/jan-kowalski-123/") == "jan-kowalski-123"
    assert slug_from_url("linkedin.com/in/Jan-Kowalski?trk=abc") == "jan-kowalski"
    assert slug_from_url("https://pl.linkedin.com/in/%C5%82ukasz-n/details/") == "łukasz-n"
    assert slug_from_url("https://www.linkedin.com/company/allegro") == ""


def test_name_lines():
    r = parse_line("Jan Kowalski, Allegro")
    assert (r.kind, r.name, r.company) == ("name", "Jan Kowalski", "Allegro")
    r = parse_line("Anna Nowak | CD Projekt")
    assert (r.name, r.company) == ("Anna Nowak", "CD Projekt")
    assert parse_line("Anna Nowak").company == ""
    assert parse_line("   ") is None
    assert parse_line("# comment") is None
    assert parse_line("12") is None


def test_parse_text_dedupes_and_rejects():
    reqs, rejected = parse_text(
        "https://www.linkedin.com/in/a-b/\nlinkedin.com/in/A-B\nJan Kowalski\n42\n"
    )
    assert [r.slug or r.name for r in reqs] == ["a-b", "Jan Kowalski"]
    assert rejected == ["42"]


def test_csv_with_header():
    text = "name;company;url\nJan Kowalski;Allegro;\nAnna Nowak;;https://www.linkedin.com/in/anowak/\n"
    reqs, rejected = parse_text(text)
    assert reqs[0].kind == "name" and reqs[0].company == "Allegro"
    assert reqs[1].kind == "url" and reqs[1].slug == "anowak" and reqs[1].name == "Anna Nowak"
    assert rejected == []
