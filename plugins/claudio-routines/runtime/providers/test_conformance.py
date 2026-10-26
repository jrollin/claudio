import pathlib
import unittest

import providers
import roles

README = pathlib.Path(__file__).parent / "README.md"
ENTRY_POINTS = ("api_client", "fetch", "plan", "parse")
SECTION_PARTS = ("### Credentials", "### Read-only", "### Hosts", "### Where each place reads the variables", '"credentials": {')


def adapters():
    return {name: providers.load(name) for name in providers.names()}


def readme_sections():
    chunks = README.read_text(encoding="utf-8").split("\n## ")[1:]
    return {name.strip(): body for name, _, body in (chunk.partition("\n") for chunk in chunks)}


def credential_names(module):
    return (*getattr(module, "CREDENTIALS", ()), *filter(None, (getattr(module, "CREDENTIAL", None),)))


class ConformanceTest(unittest.TestCase):
    def test_lists_only_modules_that_declare_a_known_role(self):
        unknown = [name for name, module in adapters().items() if getattr(module, "ROLE", None) not in roles.ROLES]

        self.assertEqual(unknown, [])

    def test_ships_an_adapter_for_every_role(self):
        self.assertEqual(sorted({getattr(module, "ROLE", None) for module in adapters().values()}), sorted(roles.ROLES))

    def test_every_adapter_exposes_the_entry_points(self):
        missing = [
            (name, entry) for name, module in adapters().items() for entry in ENTRY_POINTS if not callable(getattr(module, entry, None))
        ]

        self.assertEqual(missing, [])

    def test_every_store_adapter_exposes_parse_read_and_to_rows(self):
        missing = [
            (name, entry)
            for name, module in adapters().items()
            for entry in ("parse_read", "to_rows")
            if getattr(module, "STORE", False) and not callable(getattr(module, entry, None))
        ]

        self.assertEqual(missing, [])

    def test_every_day_filing_adapter_exposes_both_day_hooks(self):
        unpaired = [name for name, module in adapters().items() if hasattr(module, "DAY_KINDS") != callable(getattr(module, "day_row", None))]

        self.assertEqual(unpaired, [])

    def test_every_adapter_with_a_snapshot_kind_dates_it_without_a_row(self):
        missing = [name for name, module in adapters().items() if "snapshot" in getattr(module, "DAY_KINDS", {}).values() and not callable(getattr(module, "snapshot_ts", None))]

        self.assertEqual(missing, [])

    def test_every_collection_day_mapping_names_a_key_and_a_day_field(self):
        broken = [
            (name, kind)
            for name, module in adapters().items()
            for kind, rule in getattr(module, "DAY_RECORDS", {}).items()
            if not rule.get("key") or "day" not in rule
        ]

        self.assertEqual(broken, [])

    def test_every_adapter_without_a_read_store_files_its_collections_by_day(self):
        self.assertEqual([name for name, module in adapters().items() if not getattr(module, "STORE", False) and not hasattr(module, "DAY_RECORDS")], [])

    def test_slack_files_messages_by_day_and_reactions_as_snapshots(self):
        self.assertEqual(adapters()["slack"].DAY_KINDS, {"history": "span", "thread": "span", "search": "span", "reactions": "snapshot"})

    def test_slack_files_its_reads_in_the_store(self):
        self.assertIs(adapters()["slack"].STORE, True)

    def test_every_adapter_declares_its_static_headers(self):
        self.assertEqual([name for name, module in adapters().items() if not isinstance(getattr(module, "STATIC_HEADERS", None), dict)], [])

    def test_every_adapter_names_its_credentials(self):
        self.assertEqual([name for name, module in adapters().items() if not credential_names(module)], [])


class ReadmeTest(unittest.TestCase):
    def test_has_a_section_per_adapter(self):
        self.assertLessEqual(set(providers.names()), set(readme_sections()))

    def test_each_section_names_credentials_scope_hosts_and_places(self):
        sections = readme_sections()
        missing = [(name, part) for name in providers.names() for part in SECTION_PARTS if part not in sections.get(name, "")]

        self.assertEqual(missing, [])

    def test_each_section_names_the_adapter_credentials(self):
        sections = readme_sections()
        missing = [
            (name, credential)
            for name, module in adapters().items()
            for credential in credential_names(module)
            if f"`{credential}`" not in sections.get(name, "")
        ]

        self.assertEqual(missing, [])
