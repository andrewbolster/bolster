"""Integrity tests for the NI Assembly AIMS data source module.

Validates real data quality and structure from the NI Assembly API.
All network-touching tests use ``scope="class"`` fixtures to minimise
API calls.  Unit tests in ``TestValidationEdgeCases`` make no network calls.
"""

from __future__ import annotations

import pandas as pd
import pytest

from bolster.data_sources.niassembly import members, questions, votes
from bolster.data_sources.niassembly.questions import _resolve_department_id


# ── Members ──────────────────────────────────────────────────────────────────


class TestCurrentMembers:
    """Live data integrity tests for the current MLA roster."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return members.get_current_members()

    def test_current_members_count(self, df):
        """Assembly should have 85–100 MLAs (90 is standard)."""
        assert 85 <= len(df) <= 100, f"Unexpected MLA count: {len(df)}"

    def test_members_schema(self, df):
        required = {
            "PersonId",
            "MemberName",
            "MemberFirstName",
            "MemberLastName",
            "PartyName",
            "ConstituencyName",
        }
        assert required.issubset(set(df.columns)), (
            f"Missing columns: {required - set(df.columns)}"
        )

    def test_parties_present(self, df):
        """Expect at least 5 distinct parties in the Assembly."""
        parties = df["PartyName"].nunique()
        assert parties >= 5, f"Too few parties found: {parties}"

    def test_person_ids_unique(self, df):
        assert df["PersonId"].nunique() == len(df), "Duplicate PersonIds found"

    def test_person_ids_numeric(self, df):
        assert pd.api.types.is_numeric_dtype(df["PersonId"])

    def test_no_null_member_names(self, df):
        assert df["MemberName"].notna().all()

    def test_no_null_party_names(self, df):
        assert df["PartyName"].notna().all()

    def test_no_null_constituency_names(self, df):
        assert df["ConstituencyName"].notna().all()

    def test_major_parties_present(self, df):
        parties = set(df["PartyName"].unique())
        # At least a few well-known NI parties should be present
        expected_fragments = ["Sinn", "Unionist", "Alliance", "SDLP"]
        found = [f for f in expected_fragments if any(f in p for p in parties)]
        assert len(found) >= 3, f"Too few major parties found: {found}"


class TestMemberById:
    """Test single-member lookup."""

    def test_known_member_returned(self):
        df = members.get_member_by_id(5797)
        assert len(df) == 1

    def test_unknown_member_returns_empty(self):
        df = members.get_member_by_id(999999999)
        assert df.empty


# ── Votes / Divisions ─────────────────────────────────────────────────────────


class TestDivisions:
    """Live data integrity tests for Assembly divisions."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        # Fetch from start of current mandate
        return votes.get_all_divisions(start_date="2022-05-01")

    def test_divisions_not_empty(self, df):
        assert not df.empty, "No divisions returned"

    def test_at_least_100_divisions(self, df):
        assert len(df) >= 100, f"Only {len(df)} divisions found"

    def test_divisions_schema(self, df):
        required = {"DocumentID", "DivisionDate", "DivisionSubject"}
        assert required.issubset(set(df.columns)), (
            f"Missing columns: {required - set(df.columns)}"
        )

    def test_division_dates_parsed(self, df):
        assert pd.api.types.is_datetime64_any_dtype(df["DivisionDate"])

    def test_no_null_subjects(self, df):
        assert df["DivisionSubject"].notna().all()


class TestDivisionVotes:
    """Live tests for per-member vote records."""

    # Use a known stable division ID
    _KNOWN_DIVISION_ID = 406283

    @pytest.fixture(scope="class")
    def vote_df(self) -> pd.DataFrame:
        return votes.get_division_votes(self._KNOWN_DIVISION_ID)

    def test_votes_not_empty(self, vote_df):
        assert not vote_df.empty

    def test_vote_values_valid(self, vote_df):
        valid = {"AYE", "NO", "ABSTAIN"}
        found = set(vote_df["Vote"].dropna().unique())
        assert found.issubset(valid | {None}), f"Unexpected vote values: {found - valid}"

    def test_member_names_present(self, vote_df):
        assert "MemberName" in vote_df.columns
        assert vote_df["MemberName"].notna().all()


# ── Questions ────────────────────────────────────────────────────────────────


class TestQuestionsByDepartment:
    """Live data integrity tests for questions directed to a department."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return questions.get_questions_by_department("Department of Health")

    def test_questions_by_department(self, df):
        assert not df.empty, "No questions returned for Department of Health"
        assert len(df) > 100, f"Only {len(df)} questions found"

    def test_questions_schema(self, df):
        required = {"DocumentId", "TabledDate", "QuestionText"}
        assert required.issubset(set(df.columns)), (
            f"Missing columns: {required - set(df.columns)}"
        )

    def test_tabled_dates_parsed(self, df):
        assert pd.api.types.is_datetime64_any_dtype(df["TabledDate"])

    def test_no_null_question_text(self, df):
        assert df["QuestionText"].notna().all()


class TestQuestionsByMember:
    """Live tests for questions by MLA."""

    def test_questions_by_member_returns_dataframe(self):
        df = questions.get_questions_by_member(5797)
        assert isinstance(df, pd.DataFrame)
        assert len(df) >= 0  # may be empty if member has no questions

    def test_questions_by_member_schema(self):
        df = questions.get_questions_by_member(5797)
        if not df.empty:
            assert "QuestionText" in df.columns


# ── Unit tests: validate empty / malformed responses ─────────────────────────


class TestValidationEdgeCases:
    """Unit tests that do not make network calls."""

    def test_xml_to_records_empty_string(self):
        from bolster.data_sources.niassembly.members import _xml_to_records

        result = _xml_to_records("", "Root", "Item")
        assert result == []

    def test_xml_to_records_no_items(self):
        from bolster.data_sources.niassembly.members import _xml_to_records

        xml = "<Root></Root>"
        result = _xml_to_records(xml, "Root", "Item")
        assert result == []

    def test_xml_to_records_single_item(self):
        from bolster.data_sources.niassembly.members import _xml_to_records

        xml = "<Root><Item><Name>Test</Name><Id>1</Id></Item></Root>"
        result = _xml_to_records(xml, "Root", "Item")
        assert result == [{"Name": "Test", "Id": "1"}]

    def test_resolve_department_id_integer(self):
        assert _resolve_department_id(82) == 82

    def test_resolve_department_id_full_name(self):
        assert _resolve_department_id("Department of Health") == 82

    def test_resolve_department_id_abbreviation(self):
        assert _resolve_department_id("DoH") == 82

    def test_resolve_department_id_unknown_raises(self):
        with pytest.raises(ValueError, match="Cannot resolve"):
            _resolve_department_id("Ministry of Magic")

    def test_get_current_members_empty_response(self, monkeypatch):
        """get_current_members returns empty DataFrame on empty XML response."""
        import bolster.data_sources.niassembly.members as members_mod

        class FakeResponse:
            text = ""
            status_code = 200

            def raise_for_status(self):
                pass

        monkeypatch.setattr(members_mod.session, "get", lambda *a, **kw: FakeResponse())
        df = members_mod.get_current_members()
        assert isinstance(df, pd.DataFrame)
        assert df.empty

    def test_get_questions_by_department_null_response(self, monkeypatch):
        """get_questions_by_department returns empty DataFrame on null QuestionsList."""
        import bolster.data_sources.niassembly.questions as questions_mod

        class FakeResponse:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"QuestionsList": None}

        monkeypatch.setattr(
            questions_mod.session, "get", lambda *a, **kw: FakeResponse()
        )
        df = questions_mod.get_questions_by_department(82)
        assert isinstance(df, pd.DataFrame)
        assert df.empty

    def test_get_all_divisions_empty_response(self, monkeypatch):
        """get_all_divisions returns empty DataFrame when no divisions returned."""
        import bolster.data_sources.niassembly.votes as votes_mod

        class FakeResponse:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"DivisionList": None}

        monkeypatch.setattr(
            votes_mod.session, "get", lambda *a, **kw: FakeResponse()
        )
        df = votes_mod.get_all_divisions()
        assert isinstance(df, pd.DataFrame)
        assert df.empty

    def test_get_division_votes_empty_xml(self, monkeypatch):
        """get_division_votes returns empty DataFrame on empty XML."""
        import bolster.data_sources.niassembly.votes as votes_mod

        class FakeResponse:
            text = ""
            status_code = 200

            def raise_for_status(self):
                pass

        monkeypatch.setattr(
            votes_mod.session, "get", lambda *a, **kw: FakeResponse()
        )
        df = votes_mod.get_division_votes(999)
        assert isinstance(df, pd.DataFrame)
        assert df.empty

    def test_get_division_votes_no_members_in_xml(self, monkeypatch):
        """get_division_votes returns empty DataFrame when XML has no Member elements."""
        import bolster.data_sources.niassembly.votes as votes_mod

        class FakeResponse:
            text = "<MemberVoting></MemberVoting>"
            status_code = 200

            def raise_for_status(self):
                pass

        monkeypatch.setattr(
            votes_mod.session, "get", lambda *a, **kw: FakeResponse()
        )
        df = votes_mod.get_division_votes(999)
        assert isinstance(df, pd.DataFrame)
        assert df.empty
