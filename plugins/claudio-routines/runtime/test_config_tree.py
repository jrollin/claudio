import json
import os
import tempfile
import unittest

import config_tree
import roles

ROUTINE = "prod-watch"
OTHER = "chat-recap"
MARKER = "marker-" + "q7" * 4
ID = "routine-" + "3c" * 4
OTHER_ID = "routine-" + "9e" * 4


def full_transport():
    return {"cloud": "mcp", "local": "api"}


def full_preference():
    return {"cloud": ["mcp"], "local": ["api"]}


def make_source(**overrides):
    source = {"provider": "obs", "kind": "monitors"}
    source.update(overrides)
    return source


def make_routine(**overrides):
    routine = {
        "template": "prod-watch",
        "cron": "0 7 * * *",
        "sources": {"monitors": make_source(transport=full_preference())},
    }
    routine.update(overrides)
    return routine


def bare_routine(**overrides):
    return make_routine(sources={"monitors": make_source()}, **overrides)


def make_config(routines=None, **overrides):
    config = {
        "timezone": "Europe/Paris",
        "runtime": {"pin": "release-1"},
        "places": {
            "cloud": {"runtime_dir": "/opt/runtime", "state_dir": "/srv/config"},
            "local": {"runtime_dir": "/opt/local/runtime", "state_dir": "/srv/local/config"},
        },
        "providers": {"obs": {"adapter": "obsvendor"}},
        "values": {"channel": "alerts"},
    }
    if routines is not None:
        config["routines"] = routines
    config.update(overrides)
    return config


def with_default(config, transport):
    providers = {name: dict(provider, transport=transport) for name, provider in config["providers"].items()}
    return dict(config, providers=providers)


class TreeCase(unittest.TestCase):
    def tree(self, config, files=None, raw=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.directory = tmp.name
        path = os.path.join(tmp.name, "config.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(config, handle)
        folder = os.path.join(tmp.name, "config", "routines")
        for name, document in (files or {}).items():
            self.write(folder, name, json.dumps(document).encode("utf-8"))
        for name, data in (raw or {}).items():
            self.write(folder, name, data)
        return path

    def write(self, folder, name, data):
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, name), "wb") as handle:
            handle.write(data)

    def load_error(self, path, routine=None):
        with self.assertRaises(config_tree.ConfigError) as caught:
            config_tree.load(path, routine=routine)
        return str(caught.exception)


class RoutineFileNameTest(unittest.TestCase):
    def test_names_the_file_of_a_valid_slug(self):
        self.assertEqual(config_tree.routine_file(ROUTINE), "config/routines/prod-watch.json")

    def test_names_no_file_for_a_slug_that_could_widen_a_path(self):
        self.assertEqual([config_tree.routine_file(slug) for slug in ("*", "../x", "A")], [None, None, None])


class ErrorClassTest(unittest.TestCase):
    def test_exposes_the_role_config_error(self):
        self.assertIs(config_tree.ConfigError, roles.ConfigError)


class SingleFileTest(TreeCase):
    def test_returns_a_single_file_config_unchanged(self):
        routine = make_routine()
        config = make_config({ROUTINE: routine})

        self.assertEqual(config_tree.load(self.tree(config)), config)

    def test_has_no_routine_when_the_config_has_neither_routines_nor_files(self):
        config = make_config()

        self.assertEqual(config_tree.load(self.tree(config)), dict(config, routines={}))

    def test_has_no_routine_for_an_empty_routines_directory(self):
        path = self.tree(make_config(), files={})
        os.makedirs(os.path.join(self.directory, "config", "routines"))

        self.assertEqual(config_tree.load(path)["routines"], {})

    def test_rejects_a_config_that_cannot_be_read(self):
        path = os.path.join(tempfile.gettempdir(), "absent-" + MARKER, "config.json")

        self.assertTrue(self.load_error(path).startswith("config.json: cannot read"))

    def test_rejects_a_config_that_is_not_json(self):
        path = self.tree(make_config())
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{" + MARKER)

        self.assertTrue(self.load_error(path).startswith("config.json: invalid JSON"))

    def test_rejects_a_config_that_is_not_an_object(self):
        path = self.tree([])

        self.assertEqual(self.load_error(path), "config.json: must be a JSON object")

    def test_rejects_routines_that_are_not_a_mapping(self):
        path = self.tree(make_config([MARKER]))

        self.assertEqual(self.load_error(path), "config.json: routines: must be a mapping")


class RoutineFileTest(TreeCase):
    def test_merges_a_routine_file_like_the_same_inline_routine(self):
        config = with_default(make_config(), full_transport())
        inline = config_tree.load(self.tree(dict(config, routines={ROUTINE: bare_routine()})))
        filed = config_tree.load(self.tree(config, files={ROUTINE + ".json": bare_routine()}))

        self.assertEqual(filed, inline)

    def test_merges_inline_and_file_routines_into_one_map(self):
        config = make_config({OTHER: make_routine()})
        path = self.tree(config, files={ROUTINE + ".json": make_routine()})

        self.assertEqual(sorted(config_tree.load(path)["routines"]), [OTHER, ROUTINE])

    def test_ignores_files_that_do_not_end_in_json(self):
        path = self.tree(
            make_config(), files={ROUTINE + ".json": make_routine()}, raw={"notes.txt": b"{", "x.json~": b"{"}
        )

        self.assertEqual(sorted(config_tree.load(path)["routines"]), [ROUTINE])

    def test_ignores_a_backup_suffix_after_the_json_name(self):
        path = self.tree(make_config(), raw={ROUTINE + ".json.bak": b"not json"})

        self.assertEqual(config_tree.load(path)["routines"], {})

    def test_rejects_a_file_name_with_an_uppercase_letter(self):
        path = self.tree(make_config(), files={"Prod-Watch.json": make_routine()})

        self.assertEqual(
            self.load_error(path), "config/routines/Prod-Watch.json: the file name must match ^[a-z0-9-]+\\.json$"
        )

    def test_rejects_a_file_name_with_an_underscore(self):
        path = self.tree(make_config(), files={"prod_watch.json": make_routine()})

        self.assertTrue(self.load_error(path).startswith("config/routines/prod_watch.json: the file name must match"))

    def test_rejects_a_file_that_is_not_json(self):
        path = self.tree(make_config(), raw={ROUTINE + ".json": b"{" + MARKER.encode()})

        self.assertTrue(self.load_error(path).startswith("config/routines/prod-watch.json: invalid JSON"))

    def test_rejects_a_file_that_is_not_utf8(self):
        path = self.tree(make_config(), raw={ROUTINE + ".json": b'{"cron": "\xff\xfe"}'})

        self.assertEqual(self.load_error(path), "config/routines/prod-watch.json: must be UTF-8")

    def test_rejects_a_file_that_is_not_an_object(self):
        path = self.tree(make_config(), files={ROUTINE + ".json": [make_routine()]})

        self.assertEqual(self.load_error(path), "config/routines/prod-watch.json: must be a JSON object")

    def test_rejects_a_routine_file_holding_a_timezone(self):
        path = self.tree(make_config(), files={ROUTINE + ".json": make_routine(timezone="UTC")})

        self.assertEqual(
            self.load_error(path), "config/routines/prod-watch.json: timezone: belongs in config.json only"
        )

    def test_rejects_a_routine_file_holding_a_runtime(self):
        path = self.tree(make_config(), files={ROUTINE + ".json": make_routine(runtime={"pin": MARKER})})

        self.assertEqual(self.load_error(path), "config/routines/prod-watch.json: runtime: belongs in config.json only")

    def test_rejects_a_routine_file_holding_places(self):
        path = self.tree(make_config(), files={ROUTINE + ".json": make_routine(places={})})

        self.assertEqual(self.load_error(path), "config/routines/prod-watch.json: places: belongs in config.json only")

    def test_rejects_a_routine_file_holding_providers(self):
        path = self.tree(make_config(), files={ROUTINE + ".json": make_routine(providers={})})

        self.assertEqual(
            self.load_error(path), "config/routines/prod-watch.json: providers: belongs in config.json only"
        )

    def test_rejects_a_slug_defined_inline_and_as_a_file(self):
        path = self.tree(make_config({ROUTINE: make_routine()}), files={ROUTINE + ".json": make_routine()})
        message = self.load_error(path)

        self.assertIn("config.json: routines.prod-watch", message)
        self.assertIn("config/routines/prod-watch.json", message)

    def test_rejects_a_slug_clash_in_a_one_routine_load(self):
        path = self.tree(make_config({ROUTINE: make_routine()}), files={ROUTINE + ".json": make_routine()})

        self.assertIn("config/routines/prod-watch.json", self.load_error(path, ROUTINE))


class FileShapeTest(TreeCase):
    def test_rejects_a_directory_named_like_a_routine_file(self):
        path = self.tree(make_config())
        os.makedirs(os.path.join(self.directory, "config", "routines", ROUTINE + ".json"))

        self.assertTrue(self.load_error(path).startswith("config/routines/prod-watch.json: cannot read the file"))

    def test_rejects_an_empty_routine_file(self):
        path = self.tree(make_config(), raw={ROUTINE + ".json": b""})

        self.assertTrue(self.load_error(path).startswith("config/routines/prod-watch.json: invalid JSON"))

    def test_rejects_a_routine_file_with_a_byte_order_mark(self):
        path = self.tree(make_config(), raw={ROUTINE + ".json": b"\xef\xbb\xbf{}"})

        self.assertTrue(self.load_error(path).startswith("config/routines/prod-watch.json: invalid JSON"))


class IdClashTest(TreeCase):
    def test_rejects_two_files_with_one_id_naming_both_paths(self):
        files = {ROUTINE + ".json": make_routine(id=ID), OTHER + ".json": make_routine(id=ID)}
        message = self.load_error(self.tree(make_config(), files=files))

        self.assertIn("config/routines/chat-recap.json", message)
        self.assertIn("config/routines/prod-watch.json", message)

    def test_rejects_an_inline_routine_and_a_file_with_one_id(self):
        path = self.tree(make_config({OTHER: make_routine(id=ID)}), files={ROUTINE + ".json": make_routine(id=ID)})
        message = self.load_error(path)

        self.assertIn("config.json: routines.chat-recap", message)
        self.assertIn("config/routines/prod-watch.json", message)

    def test_rejects_two_inline_routines_with_one_id(self):
        message = self.load_error(self.tree(make_config({ROUTINE: make_routine(id=ID), OTHER: make_routine(id=ID)})))

        self.assertIn("config.json: routines.chat-recap", message)
        self.assertIn("config.json: routines.prod-watch", message)

    def test_never_prints_the_id(self):
        files = {ROUTINE + ".json": make_routine(id=ID), OTHER + ".json": make_routine(id=ID)}

        self.assertNotIn(ID, self.load_error(self.tree(make_config(), files=files)))

    def test_accepts_routines_with_different_ids(self):
        files = {ROUTINE + ".json": make_routine(id=ID), OTHER + ".json": make_routine(id=OTHER_ID)}

        self.assertEqual(sorted(config_tree.load(self.tree(make_config(), files=files))["routines"]), [OTHER, ROUTINE])

    def test_does_not_compare_ids_in_a_one_routine_load(self):
        path = self.tree(make_config({OTHER: make_routine(id=ID)}), files={ROUTINE + ".json": make_routine(id=ID)})

        self.assertEqual(sorted(config_tree.load(path, routine=ROUTINE)["routines"]), [OTHER, ROUTINE])


class OneRoutineTest(TreeCase):
    def test_reads_the_named_routine_file_only(self):
        files = {ROUTINE + ".json": make_routine(), OTHER + ".json": make_routine(cron="5 7 * * *")}
        config = config_tree.load(self.tree(make_config(), files=files), routine=ROUTINE)

        self.assertEqual(sorted(config["routines"]), [ROUTINE])

    def test_ignores_another_routine_file_that_is_not_json(self):
        path = self.tree(make_config(), files={ROUTINE + ".json": make_routine()}, raw={OTHER + ".json": b"{"})

        self.assertEqual(sorted(config_tree.load(path, routine=ROUTINE)["routines"]), [ROUTINE])

    def test_ignores_another_file_with_a_rejected_name(self):
        path = self.tree(make_config(), files={ROUTINE + ".json": make_routine(), "Bad_Name.json": make_routine()})

        self.assertEqual(sorted(config_tree.load(path, routine=ROUTINE)["routines"]), [ROUTINE])

    def test_ignores_another_file_holding_a_shared_key(self):
        path = self.tree(
            make_config(), files={ROUTINE + ".json": make_routine(), OTHER + ".json": make_routine(places={})}
        )

        self.assertEqual(sorted(config_tree.load(path, routine=ROUTINE)["routines"]), [ROUTINE])

    def test_rejects_the_named_routine_file_when_it_is_broken(self):
        path = self.tree(make_config(), raw={ROUTINE + ".json": b"{"})

        self.assertTrue(self.load_error(path, ROUTINE).startswith("config/routines/prod-watch.json: invalid JSON"))

    def test_keeps_the_inline_routines_next_to_the_named_file(self):
        path = self.tree(make_config({OTHER: make_routine()}), files={ROUTINE + ".json": make_routine()})

        self.assertEqual(sorted(config_tree.load(path, routine=ROUTINE)["routines"]), [OTHER, ROUTINE])

    def test_loads_an_inline_routine_when_no_file_exists(self):
        path = self.tree(make_config({ROUTINE: make_routine()}))

        self.assertEqual(sorted(config_tree.load(path, routine=ROUTINE)["routines"]), [ROUTINE])

    def test_never_lists_the_routines_directory(self):
        path = self.tree(make_config({ROUTINE: make_routine()}))
        os.makedirs(os.path.join(self.directory, "config"))
        with open(os.path.join(self.directory, "config", "routines"), "w", encoding="utf-8") as handle:
            handle.write("not a directory")

        self.assertEqual(sorted(config_tree.load(path, routine=ROUTINE)["routines"]), [ROUTINE])

    def test_reports_a_dangling_routine_file_link(self):
        path = self.tree(make_config())
        folder = os.path.join(self.directory, "config", "routines")
        os.makedirs(folder)
        os.symlink(os.path.join(self.directory, "absent.json"), os.path.join(folder, ROUTINE + ".json"))

        self.assertTrue(self.load_error(path, ROUTINE).startswith("config/routines/prod-watch.json: cannot read the file"))

    def test_rejects_a_named_routine_file_holding_a_shared_key(self):
        path = self.tree(make_config(), files={ROUTINE + ".json": make_routine(places={})})

        self.assertEqual(self.load_error(path, ROUTINE), "config/routines/prod-watch.json: places: belongs in config.json only")

    def test_rejects_a_named_routine_file_that_is_not_an_object(self):
        path = self.tree(make_config(), files={ROUTINE + ".json": [MARKER]})

        self.assertEqual(self.load_error(path, ROUTINE), "config/routines/prod-watch.json: must be a JSON object")

    def test_loads_without_the_routines_directory(self):
        path = self.tree(make_config({ROUTINE: make_routine()}))

        self.assertFalse(os.path.exists(os.path.join(self.directory, "config")))
        self.assertEqual(sorted(config_tree.load(path, routine=ROUTINE)["routines"]), [ROUTINE])

    def test_returns_the_same_routine_as_a_full_load(self):
        files = {ROUTINE + ".json": make_routine(), OTHER + ".json": make_routine(cron="5 7 * * *")}
        path = self.tree(with_default(make_config(), full_transport()), files=files)

        self.assertEqual(
            config_tree.load(path, routine=ROUTINE)["routines"][ROUTINE], config_tree.load(path)["routines"][ROUTINE]
        )

    def test_loads_the_inline_routines_for_a_slug_with_a_parent_directory(self):
        config = make_config({ROUTINE: make_routine()})
        path = self.tree(config)
        with open(os.path.join(self.directory, "x.json"), "w", encoding="utf-8") as handle:
            json.dump(make_routine(), handle)

        self.assertEqual(config_tree.load(path, routine="../../x"), config)

    def test_loads_the_inline_routines_for_a_slug_with_a_separator(self):
        config = make_config({ROUTINE: make_routine()})
        path = self.tree(config, files={"b.json": make_routine()})

        self.assertEqual(config_tree.load(path, routine="../routines/b"), config)

    def test_reads_no_file_for_an_uppercase_slug(self):
        path = self.tree(make_config(), files={ROUTINE + ".json": make_routine()})

        self.assertEqual(config_tree.load(path, routine=ROUTINE.upper())["routines"], {})

    def test_reads_no_file_for_an_empty_slug(self):
        path = self.tree(make_config(), files={".json": make_routine()})

        self.assertEqual(config_tree.load(path, routine="")["routines"], {})

    def test_reads_no_file_for_a_slug_ending_in_a_newline(self):
        path = self.tree(make_config(), files={ROUTINE + ".json": make_routine()})

        self.assertEqual(config_tree.load(path, routine=ROUTINE + "\n")["routines"], {})

    def test_keeps_an_inline_routine_whose_slug_has_another_shape_in_a_full_load(self):
        config = make_config({"Odd_Slug": make_routine()})

        self.assertEqual(config_tree.load(self.tree(config)), config)

    def test_keeps_an_inline_routine_whose_slug_has_another_shape_in_a_one_routine_load(self):
        config = make_config({"Odd_Slug": make_routine()})

        self.assertEqual(config_tree.load(self.tree(config), routine="Odd_Slug"), config)

    def test_does_not_resolve_the_transport_of_another_routine(self):
        config = make_config({ROUTINE: make_routine(), OTHER: bare_routine()})
        loaded = config_tree.load(self.tree(config), routine=ROUTINE)

        self.assertEqual(loaded["routines"][OTHER], config["routines"][OTHER])

    def test_rejects_a_broken_sibling_in_a_full_load(self):
        path = self.tree(make_config({ROUTINE: make_routine(), OTHER: bare_routine()}))

        self.assertIn("routines.chat-recap.sources.monitors.transport.cloud", self.load_error(path))

    def test_loads_the_named_routine_next_to_a_broken_inline_sibling(self):
        path = self.tree(make_config({ROUTINE: make_routine(), OTHER: bare_routine()}))

        self.assertEqual(sorted(config_tree.load(path, routine=ROUTINE)["routines"]), [OTHER, ROUTINE])

    def test_resolves_the_transport_of_the_named_routine(self):
        path = self.tree(make_config({ROUTINE: bare_routine()}))

        self.assertIn("routines.prod-watch.sources.monitors.transport.cloud", self.load_error(path, ROUTINE))


class TransportTest(TreeCase):
    def resolved(self, config, files=None, routine=None):
        return config_tree.load(self.tree(config, files=files), routine=routine)["routines"][ROUTINE]["sources"][
            "monitors"
        ]

    def test_takes_each_place_from_the_provider_default(self):
        config = with_default(make_config({ROUTINE: bare_routine()}), full_transport())

        self.assertEqual(self.resolved(config)["transport"], full_preference())

    def test_lets_a_source_value_win_over_the_provider_default(self):
        source = make_source(transport={"local": "mcp"})
        config = with_default(
            make_config({ROUTINE: make_routine(sources={"monitors": source})}), {"cloud": "api", "local": "api"}
        )

        self.assertEqual(self.resolved(config)["transport"], {"cloud": ["api"], "local": ["mcp"]})

    def test_keeps_a_complete_source_transport_when_the_provider_has_no_default(self):
        source = make_source(transport={"cloud": "api", "local": "mcp"})
        config = make_config({ROUTINE: make_routine(sources={"monitors": source})})

        self.assertEqual(self.resolved(config)["transport"], {"cloud": ["api"], "local": ["mcp"]})

    def test_resolves_a_listed_transport_to_the_list(self):
        source = make_source(transport={"cloud": ["api", "mcp"], "local": ["mcp", "api"]})
        config = make_config({ROUTINE: make_routine(sources={"monitors": source})})

        self.assertEqual(self.resolved(config)["transport"], {"cloud": ["api", "mcp"], "local": ["mcp", "api"]})

    def test_resolves_a_single_value_to_a_one_item_list(self):
        source = make_source(transport={"cloud": "api", "local": "mcp"})
        config = make_config({ROUTINE: make_routine(sources={"monitors": source})})

        self.assertEqual(self.resolved(config)["transport"], {"cloud": ["api"], "local": ["mcp"]})

    def test_takes_a_listed_default_from_the_provider(self):
        config = with_default(make_config({ROUTINE: bare_routine()}), {"cloud": ["api", "mcp"], "local": "api"})

        self.assertEqual(self.resolved(config)["transport"], {"cloud": ["api", "mcp"], "local": ["api"]})

    def test_rejects_a_repeated_transport_on_a_source(self):
        source = make_source(transport={"cloud": ["api", "api"], "local": "api"})
        path = self.tree(make_config({ROUTINE: make_routine(sources={"monitors": source})}))

        self.assertEqual(
            self.load_error(path),
            "config.json: routines.prod-watch.sources.monitors.transport.cloud: lists api more than once",
        )

    def test_rejects_a_repeated_transport_on_a_provider(self):
        path = self.tree(with_default(make_config(), {"cloud": ["mcp", "api", "mcp"]}))

        self.assertEqual(self.load_error(path), "config.json: providers.obs.transport.cloud: lists mcp more than once")

    def test_rejects_an_empty_list_on_a_source(self):
        source = make_source(transport={"cloud": [], "local": "api"})
        path = self.tree(make_config(), files={ROUTINE + ".json": make_routine(sources={"monitors": source})})

        self.assertEqual(
            self.load_error(path), "config/routines/prod-watch.json: sources.monitors.transport.cloud: must not be an empty list"
        )

    def test_rejects_an_empty_list_on_a_provider(self):
        path = self.tree(with_default(make_config(), {"local": []}))

        self.assertEqual(self.load_error(path), "config.json: providers.obs.transport.local: must not be an empty list")

    def test_rejects_a_value_other_than_api_or_mcp_inside_a_list(self):
        source = make_source(transport={"cloud": ["api", MARKER], "local": "api"})
        path = self.tree(make_config({ROUTINE: make_routine(sources={"monitors": source})}))

        message = self.load_error(path)
        self.assertEqual(
            (message, MARKER in message),
            ("config.json: routines.prod-watch.sources.monitors.transport.cloud[1]: must be one of api, mcp", False),
        )

    def test_keeps_the_other_keys_of_the_source(self):
        config = with_default(make_config({ROUTINE: bare_routine()}), full_transport())

        self.assertEqual(self.resolved(config)["kind"], "monitors")

    def test_resolves_the_transport_of_a_routine_file(self):
        config = with_default(make_config(), full_transport())

        self.assertEqual(
            self.resolved(config, files={ROUTINE + ".json": bare_routine()})["transport"], full_preference()
        )

    def test_resolves_the_transport_in_a_one_routine_load(self):
        config = with_default(make_config(), full_transport())
        source = self.resolved(config, files={ROUTINE + ".json": bare_routine()}, routine=ROUTINE)

        self.assertEqual(source["transport"], full_preference())

    def test_rejects_an_unresolved_place_of_an_inline_routine(self):
        source = make_source(transport={"cloud": "api"})
        path = self.tree(make_config({ROUTINE: make_routine(sources={"monitors": source})}))

        self.assertEqual(
            self.load_error(path),
            "config.json: routines.prod-watch.sources.monitors.transport.local: not set on the source, and its provider sets no default",
        )

    def test_rejects_an_unresolved_place_of_a_routine_file(self):
        path = self.tree(make_config(), files={ROUTINE + ".json": bare_routine()})

        self.assertEqual(
            self.load_error(path),
            "config/routines/prod-watch.json: sources.monitors.transport.cloud: not set on the source, and its provider sets no default",
        )

    def test_rejects_an_unresolved_place_when_the_provider_default_sets_the_other_place(self):
        path = self.tree(with_default(make_config(), {"local": "api"}), files={ROUTINE + ".json": bare_routine()})

        self.assertIn("sources.monitors.transport.cloud", self.load_error(path))

    def test_rejects_an_unknown_place_on_a_provider(self):
        path = self.tree(with_default(make_config(), {"cloud": "api", "moon": "api"}))

        self.assertEqual(
            self.load_error(path), "config.json: providers.obs.transport.moon: the place must be one of cloud, local"
        )

    def test_rejects_a_value_other_than_api_or_mcp_on_a_provider(self):
        path = self.tree(with_default(make_config(), {"cloud": MARKER}))

        self.assertEqual(self.load_error(path), "config.json: providers.obs.transport.cloud: must be one of api, mcp")

    def test_rejects_a_provider_transport_that_is_not_a_mapping(self):
        path = self.tree(with_default(make_config(), [MARKER]))

        self.assertEqual(self.load_error(path), "config.json: providers.obs.transport: must be a mapping")

    def test_rejects_an_invalid_provider_default_no_source_uses(self):
        path = self.tree(with_default(make_config(), {"cloud": "ftp"}))

        self.assertIn("providers.obs.transport.cloud", self.load_error(path))

    def test_rejects_an_unknown_place_on_an_inline_source(self):
        source = make_source(transport={"moon": "api"})
        path = self.tree(make_config({ROUTINE: make_routine(sources={"monitors": source})}))

        self.assertEqual(
            self.load_error(path),
            "config.json: routines.prod-watch.sources.monitors.transport.moon: the place must be one of cloud, local",
        )

    def test_rejects_a_value_other_than_api_or_mcp_on_a_source_of_a_routine_file(self):
        source = make_source(transport={"cloud": MARKER, "local": "api"})
        path = self.tree(make_config(), files={ROUTINE + ".json": make_routine(sources={"monitors": source})})

        self.assertEqual(
            self.load_error(path),
            "config/routines/prod-watch.json: sources.monitors.transport.cloud: must be one of api, mcp",
        )

    def test_leaves_a_source_transport_that_is_not_a_mapping_unchanged(self):
        config = make_config({ROUTINE: make_routine(sources={"monitors": make_source(transport="api")})})

        self.assertEqual(config_tree.load(self.tree(config)), config)

    def test_lets_the_role_check_report_a_source_transport_that_is_not_a_mapping(self):
        config = make_config({ROUTINE: make_routine(sources={"monitors": make_source(transport="api")})})
        loaded = config_tree.load(self.tree(config))

        with self.assertRaises(roles.ConfigError) as caught:
            roles.validate_config(loaded, ROUTINE, "local")
        self.assertIn("sources.monitors.transport: must be a mapping", str(caught.exception))

    def test_never_prints_a_rejected_transport_value(self):
        source = make_source(transport={"cloud": MARKER})
        provider_path = self.tree(with_default(make_config(), {"local": MARKER}))
        source_path = self.tree(make_config({ROUTINE: make_routine(sources={"monitors": source})}))

        self.assertNotIn(MARKER, self.load_error(provider_path) + self.load_error(source_path))

    def test_leaves_a_source_that_is_not_a_mapping_to_the_role_check(self):
        config = make_config({ROUTINE: make_routine(sources={"monitors": MARKER})})

        self.assertEqual(config_tree.load(self.tree(config)), config)

    def test_leaves_a_provider_that_the_config_does_not_define_to_the_role_check(self):
        config = make_config({ROUTINE: make_routine(sources={"monitors": make_source(provider="ghost")})})

        self.assertEqual(config_tree.load(self.tree(config)), config)

    def test_lets_the_role_check_report_a_provider_the_config_does_not_define(self):
        source = make_source(provider="ghost", transport=full_transport())
        loaded = config_tree.load(self.tree(make_config({ROUTINE: make_routine(sources={"monitors": source})})))

        with self.assertRaises(roles.ConfigError) as caught:
            roles.validate_config(loaded, ROUTINE, "local")
        self.assertIn("sources.monitors.provider: names no entry of providers", str(caught.exception))

    def test_leaves_a_config_whose_providers_are_not_a_mapping_to_the_role_check(self):
        config = make_config({ROUTINE: bare_routine()}, providers=[MARKER])

        self.assertEqual(config_tree.load(self.tree(config)), config)

    def test_leaves_a_routine_that_is_not_a_mapping_to_the_role_check(self):
        config = make_config({ROUTINE: MARKER})

        self.assertEqual(config_tree.load(self.tree(config)), config)

    def test_leaves_sources_that_are_not_a_mapping_to_the_role_check(self):
        config = make_config({ROUTINE: make_routine(sources=[MARKER])})

        self.assertEqual(config_tree.load(self.tree(config)), config)


class LabelTest(TreeCase):
    def test_names_the_routine_file_when_it_exists(self):
        self.tree(make_config(), files={ROUTINE + ".json": make_routine()})

        self.assertEqual(config_tree.label(self.directory, ROUTINE), "config/routines/prod-watch.json: ")

    def test_names_the_inline_key_path_when_no_file_exists(self):
        self.tree(make_config({ROUTINE: make_routine()}))

        self.assertEqual(config_tree.label(self.directory, ROUTINE), "config.json: routines.prod-watch.")

    def test_names_the_inline_key_path_when_the_directory_is_missing(self):
        self.assertEqual(
            config_tree.label(os.path.join(tempfile.gettempdir(), "absent-" + MARKER), ROUTINE),
            "config.json: routines.prod-watch.",
        )

    def test_never_builds_a_path_from_a_slug_that_is_path_like(self):
        self.tree(make_config())
        with open(os.path.join(self.directory, "x.json"), "w", encoding="utf-8") as handle:
            handle.write("{}")

        self.assertEqual(config_tree.label(self.directory, "../../x"), "config.json: routines.../../x.")


class LocateTest(TreeCase):
    def setUp(self):
        self.tree(make_config(), files={ROUTINE + ".json": make_routine(), OTHER + ".json": make_routine()})

    def test_rewrites_a_key_path_of_a_routine_kept_in_a_file(self):
        message = "routines.prod-watch.query_pack[0].rule: must be non-blank text"

        self.assertEqual(
            config_tree.locate(message, self.directory),
            "config/routines/prod-watch.json: query_pack[0].rule: must be non-blank text",
        )

    def test_rewrites_a_prefixed_message(self):
        message = "config: routines.prod-watch.query_pack[0].rule: must be non-blank text"

        self.assertEqual(
            config_tree.locate(message, self.directory),
            "config: config/routines/prod-watch.json: query_pack[0].rule: must be non-blank text",
        )

    def test_rewrites_every_routine_key_path_of_the_message(self):
        message = "routines.prod-watch.a: clashes with routines.chat-recap.b"

        self.assertEqual(
            config_tree.locate(message, self.directory),
            "config/routines/prod-watch.json: a: clashes with config/routines/chat-recap.json: b",
        )

    def test_rewrites_a_second_path_embedded_in_the_message(self):
        message = "config: routines.prod-watch.query_pack[1].key: duplicates routines.prod-watch.query_pack[0].key"

        self.assertEqual(
            config_tree.locate(message, self.directory),
            "config: config/routines/prod-watch.json: query_pack[1].key: duplicates config/routines/prod-watch.json: query_pack[0].key",
        )

    def test_rewrites_only_the_paths_of_routines_kept_in_files(self):
        message = "routines.inline-one.a: clashes with routines.chat-recap.b"

        self.assertEqual(
            config_tree.locate(message, self.directory),
            "routines.inline-one.a: clashes with config/routines/chat-recap.json: b",
        )

    def test_leaves_a_routine_key_path_without_a_following_dot(self):
        message = "routines.prod-watch: missing"

        self.assertEqual(config_tree.locate(message, self.directory), message)

    def test_leaves_a_routine_key_path_at_the_end_of_the_message(self):
        message = "see routines.prod-watch"

        self.assertEqual(config_tree.locate(message, self.directory), message)

    def test_leaves_the_message_of_a_routine_kept_inline(self):
        message = "routines.inline-one.query_pack[0].rule: must be non-blank text"

        self.assertEqual(config_tree.locate(message, self.directory), message)

    def test_leaves_a_message_without_a_routine_key_path(self):
        self.assertEqual(
            config_tree.locate("config: timezone: unknown time zone", self.directory),
            "config: timezone: unknown time zone",
        )

    def test_leaves_a_message_naming_a_longer_word(self):
        message = "myroutines.prod-watch.sources: must be a mapping"

        self.assertEqual(config_tree.locate(message, self.directory), message)

    def test_leaves_a_message_naming_a_key_under_another_path(self):
        message = "providers.routines.prod-watch.transport: must be a mapping"

        self.assertEqual(config_tree.locate(message, self.directory), message)

    def test_leaves_a_slug_that_continues_past_the_slug_characters(self):
        message = "routines.prod-watch_2.sources: must be a mapping"

        self.assertEqual(config_tree.locate(message, self.directory), message)

    def test_leaves_a_message_the_loader_already_located(self):
        path = os.path.join(self.directory, "config.json")
        os.remove(os.path.join(self.directory, "config", "routines", OTHER + ".json"))
        self.write(os.path.join(self.directory, "config", "routines"), ROUTINE + ".json", b"{")
        message = self.load_error(path)

        self.assertEqual(config_tree.locate(message, self.directory), message)

    def test_leaves_a_message_naming_both_paths_of_a_clash(self):
        path = self.tree(make_config({ROUTINE: make_routine()}), files={ROUTINE + ".json": make_routine()})
        message = self.load_error(path)

        self.assertEqual(config_tree.locate(message, self.directory), message)


SECRET_MESSAGE = "secret-key: holds a secret, name an environment variable instead"
TOKEN_MESSAGE = "token: looks like a secret, keep it in an environment variable"
SECRET_NAMES = ("password", "passwd", "secret", "token", "api_key", "apikey", "app_key", "private_key")
TOKEN_SHAPES = (
    "gh" + "p_" + "a1" * 18,
    "gh" + "s_" + "a1" * 18,
    "github" + "_pat_" + "a1" * 11,
    "xox" + "b-" + "1" * 12,
    "AK" + "IA" + "A1" * 8,
    "AS" + "IA" + "A1" * 8,
    "AI" + "za" + "a1" * 18,
    "fig" + "d_" + "a1" * 15,
    "sk" + "-ant-" + "a1" * 10,
    "sk" + "-proj-" + "a1" * 10,
    "glp" + "at-" + "a1" * 10,
    "np" + "m_" + "a1" * 18,
    "ATA" + "TT" + "a1" * 10,
    "ey" + "J" + "a1" * 4 + "." + "b2" * 6 + "." + "c3" * 6,
    "-----BEGIN " + "RSA PRIVATE KEY-----",
    "-----BEGIN " + "PRIVATE KEY-----",
)
SLACK_SHAPE = TOKEN_SHAPES[3]


def mcp_only_provider():
    return {"adapter": "obsvendor", "mcp": {"connectors": {"cloud": "obs-connector", "local": "obs-connector"}}}


class SecretGuardTest(TreeCase):
    def rejection(self, config, files=None, routine=None):
        return self.load_error(self.tree(config, files=files), routine=routine)

    def rule_of(self, message):
        return message.split(": ")[2]

    def test_rejects_a_secret_in_a_key_of_the_provider_api_of_config_json(self):
        api = {"base_url": "https://api.example.test", "password": MARKER}
        config = make_config(providers={"obs": {"adapter": "obsvendor", "api": api}})

        self.assertEqual(self.rejection(config), "config.json: providers.obs.api.password: " + SECRET_MESSAGE)

    def test_rejects_a_secret_in_a_value_of_config_json(self):
        config = make_config(values={"chat": {"token": MARKER}})

        self.assertEqual(self.rejection(config), "config.json: values.chat.token: " + SECRET_MESSAGE)

    def test_rejects_a_secret_in_a_source_option_of_an_inline_routine(self):
        config = make_config({ROUTINE: make_routine(sources={"monitors": make_source(api_key=MARKER)})})

        self.assertEqual(
            self.rejection(config), "config.json: routines.prod-watch.sources.monitors.api_key: " + SECRET_MESSAGE
        )

    def test_rejects_a_secret_in_a_source_option_of_a_routine_file(self):
        routine = make_routine(sources={"monitors": make_source(api_key=MARKER)})

        self.assertEqual(
            self.rejection(make_config(), files={ROUTINE + ".json": routine}),
            "config/routines/prod-watch.json: sources.monitors.api_key: " + SECRET_MESSAGE,
        )

    def test_rejects_a_secret_in_a_top_level_key_of_a_routine_file(self):
        routine = make_routine(secret=MARKER)

        self.assertEqual(
            self.rejection(make_config(), files={ROUTINE + ".json": routine}),
            "config/routines/prod-watch.json: secret: " + SECRET_MESSAGE,
        )

    def test_rejects_every_secret_key_name(self):
        messages = [self.rejection(make_config(values={name: MARKER})) for name in SECRET_NAMES]

        self.assertEqual(messages, [f"config.json: values.{name}: {SECRET_MESSAGE}" for name in SECRET_NAMES])

    def test_rejects_a_key_name_ending_in_a_secret_name_after_an_underscore_or_a_dash(self):
        names = ("db_password", "client-secret", "X-Api_Key", "service_app_key")
        messages = [self.rejection(make_config(values={name: MARKER})) for name in names]

        self.assertEqual(messages, [f"config.json: values.{name}: {SECRET_MESSAGE}" for name in names])

    def test_rejects_a_secret_key_name_in_any_letter_case(self):
        names = ("PASSWORD", "Token", "API_KEY", "Client_Secret")
        messages = [self.rejection(make_config(values={name: MARKER})) for name in names]

        self.assertEqual(messages, [f"config.json: values.{name}: {SECRET_MESSAGE}" for name in names])

    def test_rejects_a_secret_key_holding_something_other_than_a_variable_name(self):
        held = ("obs_key", "1OBS_KEY", "OBS-KEY", "", None, 7, True, ["OBS_KEY"])
        messages = [self.rejection(make_config(values={"token": value})) for value in held]

        self.assertEqual(messages, ["config.json: values.token: " + SECRET_MESSAGE] * len(held))

    def test_rejects_a_secret_under_a_mapping_held_by_a_secret_key(self):
        config = make_config(values={"secret": {"obs": "OBS_KEY", "chat": MARKER}})

        self.assertEqual(self.rejection(config), "config.json: values.secret.chat: " + SECRET_MESSAGE)

    def test_rejects_a_list_nested_under_a_mapping_held_by_a_secret_key(self):
        config = make_config(values={"secret": {"obs": ["OBS_KEY"]}})

        self.assertEqual(self.rejection(config), "config.json: values.secret.obs: " + SECRET_MESSAGE)

    def test_accepts_a_routine_a_provider_and_a_source_named_like_a_secret(self):
        provider = {"adapter": "obsvendor", "transport": full_transport()}
        routine = make_routine(sources={"chat-token": make_source(provider="vault-secret")})
        config = make_config({"x-token": make_routine()}, providers={"obs": provider, "vault-secret": provider})
        loaded = config_tree.load(self.tree(config, files={"y-token.json": routine}))

        self.assertEqual(sorted(loaded["routines"]), ["x-token", "y-token"])

    def test_accepts_variable_names_under_a_mapping_held_by_a_secret_key(self):
        config = make_config(values={"secret": {"obs": {"chat": "CHAT_2"}}})

        self.assertEqual(config_tree.load(self.tree(config))["values"], config["values"])

    def test_accepts_the_credentials_of_a_provider_api(self):
        credentials = {"api_key": "OBS_API_KEY", "app_key": "OBS_APP_KEY"}
        api = {"base_url": "https://api.example.test", "credentials": credentials}
        config = make_config(providers={"obs": {"adapter": "obsvendor", "api": api}})

        self.assertEqual(config_tree.load(self.tree(config))["providers"], config["providers"])

    def test_accepts_a_secret_key_holding_a_variable_name(self):
        values = {"token": "CODE_TOKEN", "password": "A", "api_key": "CHAT_2_TOKEN", "secret": "X_"}
        config = make_config(values=values)

        self.assertEqual(config_tree.load(self.tree(config))["values"], values)

    def test_accepts_key_names_that_only_look_like_a_secret_name(self):
        values = {"max_tokens": 4096, "tokens": ["a"], "token_limit": 3, "tokenizer": "t", "secretary": "s"}
        values["page_id"] = "p-1"
        config = make_config(values=values)

        self.assertEqual(config_tree.load(self.tree(config))["values"], values)

    def test_accepts_ordinary_ids_and_urls_in_values(self):
        values = {"channel": "alerts", "link": "https://example.test/dashboards/42?tab=1", "page_id": "p-" + "4" * 12}
        config = make_config(values=values)

        self.assertEqual(config_tree.load(self.tree(config))["values"], values)

    def test_loads_a_provider_read_only_through_its_connector(self):
        config = make_config(providers={"obs": mcp_only_provider()})

        self.assertEqual(config_tree.load(self.tree(config))["providers"], config["providers"])

    def test_rejects_every_known_token_shape_in_a_value(self):
        messages = [self.rejection(make_config(values={"link": shape})) for shape in TOKEN_SHAPES]

        self.assertEqual(messages, ["config.json: values.link: " + TOKEN_MESSAGE] * len(TOKEN_SHAPES))

    def test_rejects_a_token_shape_inside_a_longer_string(self):
        config = make_config(values={"link": "https://example.test/?auth=" + SLACK_SHAPE + "&x=1"})

        self.assertEqual(self.rejection(config), "config.json: values.link: " + TOKEN_MESSAGE)

    def test_rejects_a_token_in_a_provider_api_base_url(self):
        api = {"base_url": "https://" + SLACK_SHAPE + "@api.example.test"}
        config = make_config(providers={"obs": {"adapter": "obsvendor", "api": api}})

        self.assertEqual(self.rejection(config), "config.json: providers.obs.api.base_url: " + TOKEN_MESSAGE)

    def test_rejects_a_token_in_a_source_option_of_a_routine_file(self):
        routine = make_routine(sources={"monitors": make_source(note=SLACK_SHAPE)})

        self.assertEqual(
            self.rejection(make_config(), files={ROUTINE + ".json": routine}),
            "config/routines/prod-watch.json: sources.monitors.note: " + TOKEN_MESSAGE,
        )

    def test_rejects_a_token_in_an_inline_routine(self):
        config = make_config({ROUTINE: make_routine(cron=SLACK_SHAPE)})

        self.assertEqual(self.rejection(config), "config.json: routines.prod-watch.cron: " + TOKEN_MESSAGE)

    def test_rejects_a_token_inside_a_list_and_names_its_index(self):
        pack = [{"query": "up"}, {"query": "down"}, {"query": "idle"}, {"query": SLACK_SHAPE}]
        routine = make_routine(sources={"monitors": make_source(query_pack=pack)})

        self.assertEqual(
            self.rejection(make_config(), files={ROUTINE + ".json": routine}),
            "config/routines/prod-watch.json: sources.monitors.query_pack[3].query: " + TOKEN_MESSAGE,
        )

    def test_rejects_a_token_held_directly_by_a_list(self):
        config = make_config(values={"links": ["https://example.test", SLACK_SHAPE]})

        self.assertEqual(self.rejection(config), "config.json: values.links[1]: " + TOKEN_MESSAGE)

    def test_rejects_a_secret_inside_a_mapping_of_a_list(self):
        config = make_config(values={"hooks": [{"url": "https://example.test"}, {"password": MARKER}]})

        self.assertEqual(self.rejection(config), "config.json: values.hooks[1].password: " + SECRET_MESSAGE)

    def test_reports_a_secret_key_before_a_token_shape_under_the_same_key(self):
        config = make_config(values={"token": SLACK_SHAPE})

        self.assertEqual(self.rule_of(self.rejection(config)), "secret-key")

    def test_scans_a_token_shape_held_by_a_non_secret_key_only_as_a_token(self):
        config = make_config(values={"note": SLACK_SHAPE})

        self.assertEqual(self.rule_of(self.rejection(config)), "token")

    def test_rejects_a_key_shaped_like_a_token(self):
        config = make_config(values={SLACK_SHAPE: "alerts"})

        self.assertEqual(self.rejection(config), "config.json: values: token: a key looks like a secret, keep it in an environment variable")

    def test_never_prints_a_key_shaped_like_a_token(self):
        config = make_config(values={SLACK_SHAPE: "alerts"})

        self.assertNotIn(SLACK_SHAPE, self.rejection(config))

    def test_rejects_camel_case_and_dashed_secret_names(self):
        for name in ("api-key", "x-api-key", "DD-API-KEY", "appKey", "privateKey", "clientSecret", "accessToken", "apiKey"):
            with self.subTest(name=name):
                self.assertEqual(self.rule_of(self.rejection(make_config(values={name: MARKER}))), "secret-key")

    def test_accepts_camel_case_and_dashed_secret_names_holding_variable_names(self):
        values = {name: "SOME_VARIABLE" for name in ("api-key", "x-api-key", "DD-API-KEY", "appKey", "privateKey", "clientSecret", "accessToken")}

        self.assertEqual(config_tree.load(self.tree(make_config(values=values)))["values"], values)

    def test_rejects_a_token_shaped_variable_name_under_a_secret_key(self):
        config = make_config(values={"api_key": "AKIA" + "Q" * 16})

        self.assertEqual(self.rule_of(self.rejection(config)), "token")

    def test_reports_the_first_finding_in_sorted_key_order(self):
        config = make_config(values={"b_token": MARKER, "a_note": SLACK_SHAPE})

        self.assertEqual(self.rejection(config), "config.json: values.a_note: " + TOKEN_MESSAGE)

    def test_scans_config_json_before_the_routine_files(self):
        config = make_config(values={"token": MARKER})
        files = {ROUTINE + ".json": make_routine(token=MARKER)}

        self.assertEqual(self.rejection(config, files=files), "config.json: values.token: " + SECRET_MESSAGE)

    def test_scans_a_routine_file_before_its_shared_key_check(self):
        files = {ROUTINE + ".json": make_routine(timezone="UTC", token=MARKER)}

        self.assertEqual(
            self.rejection(make_config(), files=files), "config/routines/prod-watch.json: token: " + SECRET_MESSAGE
        )

    def test_names_the_file_of_another_routine_in_a_full_load(self):
        files = {ROUTINE + ".json": make_routine(), OTHER + ".json": make_routine(token=MARKER)}

        self.assertEqual(
            self.rejection(make_config(), files=files), "config/routines/chat-recap.json: token: " + SECRET_MESSAGE
        )

    def test_does_not_scan_the_file_of_another_routine_in_a_one_routine_load(self):
        files = {ROUTINE + ".json": make_routine(), OTHER + ".json": make_routine(token=MARKER)}
        path = self.tree(make_config(), files=files)

        self.assertEqual(sorted(config_tree.load(path, routine=ROUTINE)["routines"]), [ROUTINE])

    def test_scans_the_file_of_the_routine_in_a_one_routine_load(self):
        files = {ROUTINE + ".json": make_routine(token=MARKER), OTHER + ".json": make_routine()}

        self.assertEqual(
            self.rejection(make_config(), files=files, routine=ROUTINE),
            "config/routines/prod-watch.json: token: " + SECRET_MESSAGE,
        )

    def test_scans_config_json_in_a_one_routine_load(self):
        config = make_config(values={"token": MARKER})
        files = {ROUTINE + ".json": make_routine()}

        self.assertEqual(
            self.rejection(config, files=files, routine=ROUTINE), "config.json: values.token: " + SECRET_MESSAGE
        )

    def test_never_prints_the_value_of_a_secret_key(self):
        config = make_config(values={"chat": {"token": MARKER}})

        self.assertNotIn(MARKER, self.rejection(config))

    def test_never_prints_a_token_shaped_value(self):
        config = make_config(values={"note": "xox" + "b-" + MARKER})

        self.assertNotIn(MARKER, self.rejection(config))

    def test_never_prints_a_value_found_in_a_routine_file(self):
        files = {ROUTINE + ".json": make_routine(sources={"monitors": make_source(api_key=MARKER)})}

        self.assertNotIn(MARKER, self.rejection(make_config(), files=files))


class EngineKeyTest(TreeCase):
    def rejection(self, engine, in_file=False):
        routine = make_routine(engine=engine)
        if in_file:
            path = self.tree(make_config(), files={ROUTINE + ".json": routine})
        else:
            path = self.tree(make_config({ROUTINE: routine}))
        return self.load_error(path, routine=ROUTINE)

    def loaded(self, **overrides):
        return config_tree.load(self.tree(make_config({ROUTINE: make_routine(**overrides)})), routine=ROUTINE)["routines"][ROUTINE]

    def test_loads_a_routine_without_an_engine(self):
        self.assertNotIn("engine", self.loaded())

    def test_loads_the_tribe_engine(self):
        self.assertEqual(self.loaded(engine="tribe")["engine"], "tribe")

    def test_loads_the_watch_engine(self):
        self.assertEqual(self.loaded(engine="watch")["engine"], "watch")

    def test_loads_the_recap_engine(self):
        self.assertEqual(self.loaded(engine="recap")["engine"], "recap")

    def test_rejects_an_unknown_engine_naming_the_key_path(self):
        self.assertEqual(self.rejection("other"), "config.json: routines.prod-watch.engine: must be one of watch, tribe, recap, weekly")

    def test_rejects_an_unknown_engine_in_a_routine_file_naming_the_file(self):
        self.assertEqual(self.rejection("other", in_file=True), "config/routines/prod-watch.json: engine: must be one of watch, tribe, recap, weekly")

    def test_rejects_a_null_engine(self):
        self.assertEqual(self.rejection(None), "config.json: routines.prod-watch.engine: must be one of watch, tribe, recap, weekly")


if __name__ == "__main__":
    unittest.main()
