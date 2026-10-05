import unittest
import sys
import types
from unittest.mock import patch

from plight_nlp_inspector import evaluate_expression, parse_local, parse_with_rpgnlp


class LocalParserTests(unittest.TestCase):
    def test_attack_extracts_target_and_instrument(self):
        result = parse_local("Attack the goblin with two daggers")
        occurrence = result["occurrences"][0]
        self.assertEqual(occurrence["action_id"], "attack")
        self.assertEqual(occurrence["arguments"]["subject"], "goblin")
        self.assertEqual(
            occurrence["arguments"]["objects"],
            [{"name": "daggers", "quantity": 2}],
        )

    def test_equip_extracts_hand_and_item(self):
        result = parse_local("Equip the iron sword in my right hand")
        occurrence = result["occurrences"][0]
        self.assertEqual(occurrence["action_id"], "equip_item")
        self.assertEqual(occurrence["arguments"]["item"]["name"], "iron sword")
        self.assertEqual(occurrence["arguments"]["slot"], "right_hand")

    def test_inventory_phrases_are_observe_with_canonical_subjects(self):
        examples = {
            "observe my inventory": "inventory",
            "look in my inventory": "inventory",
            "what am I carrying?": "inventory",
            "observe armor": "armor",
            "observe hands": "hands",
            "observe weapons": "weapons",
        }
        for text, subject in examples.items():
            with self.subTest(text=text):
                occurrence = parse_local(text)["occurrences"][0]
                self.assertEqual(occurrence["action_id"], "observe")
                self.assertEqual(occurrence["arguments"]["subject"], subject)

    def test_unequip_extracts_slot_or_item(self):
        slot_occurrence = parse_local("unequip my right hand")["occurrences"][0]
        self.assertEqual(slot_occurrence["action_id"], "unequip_item")
        self.assertEqual(slot_occurrence["arguments"]["slot"], "right_hand")
        item_occurrence = parse_local("take off the iron sword")["occurrences"][0]
        self.assertEqual(item_occurrence["action_id"], "unequip_item")
        self.assertEqual(item_occurrence["arguments"]["item"]["name"], "iron sword")

    def test_travel_extracts_direction(self):
        result = parse_local("Run north east")
        self.assertEqual(result["occurrences"][0]["action_id"], "travel")
        self.assertEqual(result["occurrences"][0]["arguments"]["direction"], "north east")

    def test_observe_extracts_entity_target(self):
        result = parse_local("look at the forest rat")
        occurrence = result["occurrences"][0]
        self.assertEqual(occurrence["action_id"], "observe")
        self.assertEqual(occurrence["arguments"]["subject"], "forest rat")

    def test_observe_area_phrasing_does_not_create_entity_target(self):
        for text in ("look", "look around", "look at the area", "examine my surroundings"):
            with self.subTest(text=text):
                result = parse_local(text)
                self.assertEqual(result["occurrences"][0]["action_id"], "observe")
                self.assertNotIn("subject", result["occurrences"][0]["arguments"])

    def test_observe_self_phrasing_uses_self_subject(self):
        for text in (
            "look at myself",
            "look at me",
            "observe my profile",
            "view my profile",
            "look at my character",
        ):
            with self.subTest(text=text):
                occurrence = parse_local(text)["occurrences"][0]
                self.assertEqual(occurrence["action_id"], "observe")
                self.assertEqual(occurrence["arguments"]["subject"], "self")

    def test_talk_preserves_utterance_and_topic(self):
        result = parse_local('Tell the guard about the plan: "attack the troll or flee"')
        args = result["occurrences"][0]["arguments"]
        self.assertEqual(result["occurrences"][0]["action_id"], "talk")
        self.assertEqual(args["subject"], "guard")
        self.assertEqual(args["topic"], "plan")
        self.assertEqual(args["utterance"], "attack the troll or flee")
        self.assertEqual(len(result["occurrences"]), 1)

    def test_action_chain_preserves_order_and_conjunction(self):
        result = parse_local("Attack the rat then travel north")
        self.assertEqual([item["action_id"] for item in result["occurrences"]], ["attack", "travel"])
        self.assertEqual(result["expression"]["operator"], "and")
        self.assertEqual(result["satisfying_assignments_preview"], [["action-1", "action-2"]])

    def test_or_has_three_satisfying_assignments(self):
        result = parse_local("Attack the rat or defend")
        self.assertEqual(
            result["satisfying_assignments_preview"],
            [["action-1"], ["action-2"], ["action-1", "action-2"]],
        )

    def test_negation_selects_no_actions(self):
        result = parse_local("Do not attack the rat")
        self.assertEqual(result["expression"]["operator"], "not")
        self.assertEqual(result["satisfying_assignments_preview"], [[]])

    def test_prefix_negation_applies_to_first_operand_in_a_chain(self):
        result = parse_local("Do not attack the rat or defend")
        self.assertEqual(result["expression"]["operator"], "or")
        self.assertEqual(result["expression"]["children"][0]["operator"], "not")
        self.assertEqual(
            result["satisfying_assignments_preview"],
            [[], ["action-2"], ["action-1", "action-2"]],
        )

    def test_only_if_is_implication(self):
        result = parse_local("Attack the rat only if I defend")
        self.assertEqual(result["expression"]["operator"], "implies")
        self.assertEqual(len(result["satisfying_assignments_preview"]), 3)

    def test_operator_truth_tables(self):
        expected = {
            "and": [["action-1", "action-2"]],
            "or": [["action-1"], ["action-2"], ["action-1", "action-2"]],
            "xor": [["action-1"], ["action-2"]],
            "nand": [[], ["action-1"], ["action-2"]],
            "nor": [[]],
            "xnor": [[], ["action-1", "action-2"]],
            "iff": [[], ["action-1", "action-2"]],
            "implies": [[], ["action-2"], ["action-1", "action-2"]],
            "converse": [[], ["action-1"], ["action-1", "action-2"]],
        }
        for operator, assignments in expected.items():
            with self.subTest(operator=operator):
                command = f"Attack the rat {operator} defend"
                result = parse_local(command)
                self.assertEqual(result["satisfying_assignments_preview"], assignments)

    def test_if_then_is_implication(self):
        result = parse_local("If I attack the rat then defend")
        self.assertEqual(result["expression"]["operator"], "implies")
        self.assertEqual(
            result["satisfying_assignments_preview"],
            [[], ["action-2"], ["action-1", "action-2"]],
        )


    def test_symbolic_operators_are_rejected(self):
        result = parse_local("Attack the rat && defend")
        self.assertEqual(result["status"], "no_parse")

    def test_fallback_selects_best_supported_action(self):
        result = parse_local("observ")
        self.assertEqual(result["status"], "selected")
        self.assertEqual(result["occurrences"][0]["action_id"], "observe")
        self.assertEqual(result["rank_source"], "local_alias_fallback")

    def test_boolean_evaluator_handles_implication(self):
        result = parse_local("Attack the rat implies defend")
        expression = result["expression"]
        self.assertTrue(
            evaluate_expression(expression_from_dict(expression), {"action-1": False, "action-2": False})
        )
        self.assertFalse(
            evaluate_expression(expression_from_dict(expression), {"action-1": True, "action-2": False})
        )

    def test_rpgnlp_adapter_maps_canonical_action_and_fields(self):
        class FakeEngine:
            def run(self, text):
                self.text = text
                return {
                    "action": "light_attack",
                    "subject": "goblin",
                    "direction": "",
                    "instrument": [{"name": "dagger", "quantity": 1}],
                    "modifiers": ["quickly"],
                    "topic": "",
                }

        fake_module = types.ModuleType("rpgnlp")
        fake_module.NLPEngine = FakeEngine
        with patch.dict(sys.modules, {"rpgnlp": fake_module}):
            result = parse_with_rpgnlp("poke the goblin quickly")
        occurrence = result["occurrences"][0]
        self.assertEqual(occurrence["action_id"], "light_attack")
        self.assertEqual(occurrence["arguments"]["subject"], "goblin")
        self.assertEqual(occurrence["arguments"]["objects"][0]["name"], "dagger")


def expression_from_dict(value):
    from plight_nlp_inspector import Expression

    return Expression(
        operator=value["operator"],
        occurrence_id=value.get("occurrence_id"),
        children=tuple(expression_from_dict(child) for child in value.get("children", [])),
    )


if __name__ == "__main__":
    unittest.main()
