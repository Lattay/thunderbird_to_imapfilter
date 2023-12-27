#!/usr/bin/env python3
from __future__ import annotations
from typing import Optional, Iterable

import re
import sys
from os import walk
from os.path import join, basename, isdir, expanduser
from dataclasses import dataclass, field


ALL_ADDRESSES = ["from", "to", "cc", "bcc"]
LITERAL_FIELDS = ["body", "subject", *ALL_ADDRESSES]

RECORD = re.compile(r'^(\w+)="(.*)"$')

ACTION_PARAMETER_FOLDER = re.compile(
    r"^imap://([^&$+,/:;=?@# <>\[\]{}|\\^]+)@([^&$+,/:;=?@# <>\[\]{}|\\^%]+)/(.*)$"
)

ACTION_PARAMETER_ADDRESS = re.compile(
    r"^[^&$+,/:;=?@# <>\[\]{}|\\^]+@[^&$+,/:;=?@# <>\[\]{}|\\^%]+$"
)


AND_SET = re.compile(r"AND \((.*?,.*?,.*?)\)")
OR_SET = re.compile(r"OR \((.*?,.*?,.*?)\)")

REMOTE_TEMPLATE = """\
{varname} = IMAP {{
    server = '{servername}',
    username = 'USERNAME',
    password = 'PASSWORD',
    ssl = 'auto'
}}
"""


def main(root: str) -> str:
    filters = []

    if not valid(root):
        raise FileNotFoundError(f'"{root}" is not a valid directory.')

    for dir, _, files in walk(join(root, "ImapMail")):
        if "msgFilterRules.dat" in files:
            filters.append((join(dir, "msgFilterRules.dat"), dir))

    rules = {}
    box = set()

    for filter_file, dir in filters:
        these_rules, this_box = get_rules(filter_file, dir)
        rules.update(these_rules)
        box.add(this_box)

    return render_script(rules, box)


class MethodCallPredicate:
    "A message selector based on a imapfilter method."

    def __init__(self, filter: str):
        self.filter = filter

    def render(self, base, indent=0) -> str:
        return f"{base}:{self.filter}"


class Combinator:
    "Combine predicated."

    sep: str

    def __init__(self, conds: Iterable["MethodCallPredicate | Combinator | str"]):
        self.conds = [
            cond
            if isinstance(cond, (Combinator, MethodCallPredicate))
            else MethodCallPredicate(cond)
            for cond in conds
        ]

    def render(self, base, indent=4) -> str:
        if len(self.conds) == 0:
            return "()"
        elif len(self.conds) == 1:
            return self.conds[0].render(base, indent)
        else:
            spaces = " " * (indent + 4)
            return (
                "("
                + f"\n{spaces}{self.sep} ".join(
                    e.render(base, indent + 1) for e in self.conds
                )
                + ")"
            )


class OrCombinator(Combinator):
    sep = "+"


class AndCombinator(Combinator):
    sep = "*"


@dataclass
class Action:
    "Action to perform on a selection of messages."

    type: str
    value: Optional[str] = None


@dataclass
class Rule:
    "A filtering rule."

    name: str
    box: str
    condition: Optional[Combinator] = None
    actions: list[Action] = field(default_factory=list)


def get_rules(filter_file: str, dir: str) -> tuple[dict[str, Rule], str]:
    "Read the rules from a file."
    box = basename(dir)
    rules: dict[str, Rule] = {}
    current_rule: str = "not a rule"

    with open(filter_file) as f:
        for line in f:
            key, val = parse_record(line)
            if key == "name":
                current_rule = val
                rules[val] = Rule(val, basename(dir))
                continue

            if current_rule not in rules:
                assert key not in {
                    "action",
                    "actionValue",
                    "condition",
                }, "Corrupted file. Rule field outside a rule."
                continue

            if key == "action":  # start a new action
                rules[current_rule].actions.append(Action(val))

            elif key == "actionValue":
                if len(rules[current_rule].actions) < 1:
                    raise ValueError("No action specified before actionValue.")
                rules[current_rule].actions[-1].value = val

            elif key == "condition":
                rules[current_rule].condition = parse_combinator(val)

    return rules, box


def parse_record(line: str) -> tuple[str, str]:
    "Parse record in msgFilterRules.dat"
    m = RECORD.match(line.strip())
    if not m:
        raise ValueError(f'Unsupported line format "{line.strip()}".')
    return m.group(1), m.group(2)


def parse_action_parameter(
    value: str,
) -> tuple[str, tuple[Optional[str], Optional[str]], str]:
    "Convert thunderbird actionValue into imapfilter method call."
    if m := ACTION_PARAMETER_FOLDER.match(value):
        username, servername, directory = m[1], m[2], m[3]
        return ("directory", (servername, username), directory)
    elif m := ACTION_PARAMETER_ADDRESS.match(value):
        return ("address", (None, None), value)
    else:
        raise ValueError(f'Unsupported actionValue "{value}".')


def parse_combinator(value: str) -> Combinator:
    "A combinator is a way of combining several predicates into one."
    if conds := AND_SET.findall(value):
        return AndCombinator(map(parse_condition, conds))
    elif conds := OR_SET.findall(value):
        return OrCombinator(map(parse_condition, conds))
    else:
        raise ValueError(f'Unsupported condition format "{value}".')


def parse_condition(string: str) -> Combinator | MethodCallPredicate:
    "Parse a single condition."
    obj, verb, compl = string.split(",")

    if verb == "contains":
        if obj in LITERAL_FIELDS:
            return MethodCallPredicate(f"contain_{obj}('{compl}')")
        elif obj == "all addresses":
            return OrCombinator(f"contain_{obj}('{compl}')" for obj in ALL_ADDRESSES)

    elif verb == "begins with":
        if obj in LITERAL_FIELDS:
            return MethodCallPredicate(f"match_{obj}('^{quote(compl)}.*')")
        elif obj == "all addresses":
            return OrCombinator(
                f"match_{obj}('^{quote(compl)}.*')" for obj in ALL_ADDRESSES
            )

    elif verb == "is greater than" and obj == "size":
        return MethodCallPredicate(f"is_larger({compl})")

    elif verb == "is less than" and obj == "size":
        return MethodCallPredicate(f"is_smaller({compl})")

    # if no return happened earlier throw
    raise ValueError(f'Unimplemented condition transformation "{obj} {verb} {compl}"')


def render_script(rules: dict[str, Rule], boxes: Iterable[str]) -> str:
    "Produce a string containing the complete imapfilter script."

    varnames = {}
    script = []
    for servername in boxes:
        varnames[servername] = varname = make_unique_varname(servername)
        script.append(REMOTE_TEMPLATE.format(varname=varname, servername=servername))

    for rule in rules.values():
        try:
            script.append(render_rule(rule, varnames))
        except ValueError as e:
            log_error(f"WARNING: {e} Ignoring the corresponding rule.")
            continue

    return "\n\n".join(script)


def render_rule(rule: Rule, boxes: dict[str, str]) -> str:
    varname = boxes[rule.box]
    inbox = f"{varname}.INBOX"
    cond = rule.condition and rule.condition.render(inbox)
    return "\n".join(
        f"msgs = {cond}\nmsgs:{render_action(boxes, action)}" for action in rule.actions
    )


def render_action(boxes: dict[str, str], action: Action) -> str:
    "Convert thunderbird action into imap_filter method call."

    def noop(_):
        return ""

    def format_folder(action_spec):
        _, (server, address), folder = action_spec
        box = boxes[server]
        return f"{box}['{folder}']"

    actions = {
        "Delete": ("delete_messages()", noop),
        "Move to folder": ("move_messages({})", format_folder),
        "Mark read": ("mark_seen()", noop),
    }

    if action.type not in actions:
        raise ValueError(f"Unimplemented action {action.type}.")
    else:
        func, formatter = actions[action.type]

    if action.value:
        return func.format(formatter(parse_action_parameter(action.value)))
    else:
        return func


_varnames = set()


def make_unique_varname(servername: str) -> str:
    base = "_".join(
        elem.replace("-", "_")
        # remove the last element of the server name
        for elem in servername.split(".")[:-1]
        # remove the usual server prefixes
        if elem not in {"imap", "imaps", "mail"}
    )

    if base == "":  # should never happen, but just in case
        base = "remote"

    # ensure unicity
    c = 1
    candidate = base
    while candidate in _varnames:
        c += 1
        candidate = base + f"_{c}"

    _varnames.add(candidate)
    return candidate


def valid(path: str) -> bool:
    "Is path a valid directory?"
    return isdir(path)


def log_error(msg: str):
    print(msg, file=sys.stderr)


def quote(s: str) -> str:
    "Escape regex special characters."
    return (
        s.replace("[", "\\[")
        .replace("]", "\\]")
        .replace(".", "\\.")
        .replace("*", "\\*")
        .replace("?", "\\?")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace("|", "\\|")
        .replace("^", "\\^")
        .replace("$", "\\$")
        .replace("+", "\\+")
    )


if __name__ == "__main__":
    if len(sys.argv) <= 1 or "-h" in sys.argv or "--help" in sys.argv:
        print("Usage: python3 {sys.argv[0]} <Thunderbird profile path>")
    else:
        root = expanduser(sys.argv[1])
        print(main(root))
