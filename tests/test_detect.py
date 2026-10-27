from incraw.detect import LIKELY, NOT_DETECTED, OPEN, detect

TOP_OPEN_CARD = """Jan Kowalski
He/Him
Senior Backend Engineer | Python
Warsaw, Masovian District, Poland
Contact info
500+ connections
Open to work
Backend Engineer, Software Engineer and Python Developer roles
Show details
Message
More"""


def test_photo_frame_is_open():
    d = detect({"imgAlts": ["Jan Kowalski, #OPENTOWORK"], "topText": "", "headline": "Engineer"})
    assert d.status == OPEN
    assert d.signals[0].kind == "photo_frame"


def test_card_is_open_with_roles():
    d = detect({"imgAlts": ["Jan Kowalski"], "topText": TOP_OPEN_CARD, "headline": "Senior Backend Engineer | Python"})
    assert d.status == OPEN
    assert d.roles.startswith("Backend Engineer")


def test_headline_only_is_likely():
    for h in ("Data Analyst | Looking for new opportunities", "Java Dev – otwarty na nowe oferty",
              "UX designer, #OpenToWork", "Szukam pracy jako tester"):
        assert detect({"headline": h}).status == LIKELY, h


def test_nothing_is_not_detected():
    d = detect({"imgAlts": ["Anna Nowak"], "topText": "Anna Nowak\nCTO at X\nShow recruiters you're open to work",
                "headline": "CTO at X"})
    assert d.status == NOT_DETECTED


def test_2026_layout_framed_photo_is_open():
    # new layout: photo alt is empty, the frame is baked into a "framedphoto" image
    d = detect({"imgAlts": ["Cover photo"], "headline": "Analyst",
                "imgSrcs": ["https://media.licdn.com/dms/image/v2/X/profile-framedphoto-shrink_200_200/0/1"],
                "viewNames": ["profile-top-card", "profile-top-card-member-photo"]})
    assert d.status == OPEN and d.signals[0].kind == "photo_frame"


def test_2026_layout_framed_photo_with_hiring_is_not_open():
    d = detect({"imgSrcs": ["https://media.licdn.com/x/profile-framedphoto-shrink_200_200/0/1"],
                "viewNames": ["profile-top-card", "profile-top-card-hiring"]})
    assert d.status == NOT_DETECTED


def test_own_profile_open_to_button_is_not_a_signal():
    d = detect({"imgSrcs": ["https://media.licdn.com/x/profile-displayphoto-shrink_100_100/0/1"],
                "viewNames": ["profile-top-card", "profile-opento-button", "profile-dismiss-open-to"],
                "topText": "Jakub Komorný\nStrategic IT Enabler @aardwark\nOpen to\nAdd section",
                "headline": "Strategic IT Enabler @aardwark"})
    assert d.status == NOT_DETECTED and d.signals == []


def test_hiring_frame_is_not_open():
    d = detect({"imgAlts": ["Anna Nowak, #HIRING"], "headline": "Talent Partner"})
    assert d.status == NOT_DETECTED
    assert d.signals[0].kind == "hiring"
