import pytest

from apps.companieshouse import people


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("SMITH, Jane Anne", ("", "Jane", "Anne", "Smith")),
        ("SAMPLE, Alice", ("", "Alice", "", "Sample")),
        ("SMITH-JONES, Mary Ellen Rose", ("", "Mary", "Ellen Rose", "Smith-Jones")),
        ("O'BRIEN, Sean", ("", "Sean", "", "O'Brien")),
        ("MCDONALD, Ewan", ("", "Ewan", "", "McDonald")),
        ("VAN DER BERG, Anna", ("", "Anna", "", "Van Der Berg")),
        ("TESTER, Robert, Dr", ("Dr", "Robert", "", "Tester")),
        ("TESTER, Sir Robert", ("Sir", "Robert", "", "Tester")),
        ("Robert Tester", ("", "Robert", "", "Tester")),
        ("", ("", "", "", "")),
    ],
)
def test_officer_names_are_parsed(raw, expected):
    parsed = people.parse_officer_name(raw)
    assert (
        parsed["title"],
        parsed["first_name"],
        parsed["middle_name"],
        parsed["last_name"],
    ) == expected


def test_officer_id_comes_from_the_appointments_link():
    item = {"links": {"officer": {"appointments": "/officers/AbC123xyz/appointments"}}}
    assert people.officer_id(item) == "AbC123xyz"
    assert people.officer_id({}) == ""


def test_an_owner_who_is_also_a_director_is_one_person():
    officers = [
        {
            "name": "SAMPLE, Alice Jane",
            "officer_role": "director",
            "appointed_on": "2015-03-12",
            "date_of_birth": {"month": 6, "year": 1980},
            "links": {"officer": {"appointments": "/officers/X1/appointments"}},
        },
        {"name": "EXAMPLE NOMINEES LIMITED", "officer_role": "corporate-secretary"},
    ]
    owners = [
        {
            "kind": "individual-person-with-significant-control",
            "name": "Mrs Alice Jane Sample",
            "name_elements": {"forename": "Alice", "surname": "Sample", "title": "Mrs"},
            "date_of_birth": {"month": 6, "year": 1980},
            "notified_on": "2016-04-06",
        },
        {"kind": "corporate-entity-person-with-significant-control", "name": "Holdco Ltd"},
    ]
    found = people.people_from(officers, owners)
    assert len(found) == 1
    assert found[0].roles == {"director", "psc"}
    assert found[0].officer_id == "X1"
