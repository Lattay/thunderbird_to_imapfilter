#!/usr/bin/env python3
import os
import re
import sys
from copy import deepcopy


def main(root):

    filters = set()

    for dir, _, files in os.walk(os.path.join(root, 'ImapMail')):
        if 'msgFilterRules.dat' in files:
            filters.add((os.path.join(dir, 'msgFilterRules.dat'), dir))

    rules = {}
    box = set()

    for filter_file, dir in filters:
        base_rule = {'box': os.path.basename(dir), 'actions': []}
        box.add(base_rule['box'])
        current_rule = {}
        with open(filter_file) as f:
            for line in f:
                key, val = parse(line)
                try:
                    if key == 'name':
                        if (
                            'name' in current_rule
                        ):  # a previous rule have been filled already
                            rules[current_rule['name']] = current_rule
                        current_rule = deepcopy(base_rule)
                        current_rule['name'] = val

                    elif key == 'action':  # start a new action
                        current_rule['actions'].append({'type': val})

                    elif key == 'actionValue':
                        assert len(current_rule['actions']) >= 1
                        current_rule['actions'][-1]['value'] = val

                    elif key == 'condition':
                        current_rule['condition'] = convert_condition(val)
                except Exception as e:
                    print(key, val)
                    raise e
        if 'name' in current_rule:
            rules[current_rule['name']] = current_rule

    return dump_rules(rules, box)


record = re.compile(r'^(\w+)="(.*)"$')


def valid(path):
    return os.path.isdir(path)


def parse(line):
    '''
    Very naive algorithm
    '''
    m = record.match(line.strip())
    if not m:
        raise ValueError(f'Unsupported line format "{line.strip()}".')
    return m.group(1), m.group(2)


action_params_folder = re.compile(
    r'^imap://([^&$+,/:;=?@# <>\[\]{}|\\^]+)@([^&$+,/:;=?@# <>\[\]{}|\\^%]+)/(.*)$'
)
action_params_address = re.compile(
    r'^[^&$+,/:;=?@# <>\[\]{}|\\^]+@[^&$+,/:;=?@# <>\[\]{}|\\^%]+$'
)


def convert_action_params(value):
    if m := action_params_folder.match(value):
        username, servername, directory = m[1], m[2], m[3]
        return ('directory', (servername, username), directory)
    elif m := action_params_address.match(value):
        return ('address', (None, None), value)
    else:
        raise ValueError(f'Unsupported actionValue "{value}".')


and_set_re = re.compile(r'AND \((.*?,.*?,.*?)\)')
or_set_re = re.compile(r'OR \((.*?,.*?,.*?)\)')


def convert_condition(value):
    if conds := and_set_re.findall(value):
        return AndCond(map(parse_cond, conds))
    elif conds := or_set_re.findall(value):
        return OrCond(map(parse_cond, conds))
    else:
        raise ValueError(f'Unsupported condition format "{value}".')


def parse_cond(string):
    '''
    Transform thunderbird conditions into imapfilter sets method calls.
    '''
    obj, verb, compl = string.split(',')
    if verb == 'contains':
        if obj in {'from', 'subject', 'bcc', 'cc', 'to', 'body'}:
            return LiteralCond(f'contain_{obj}(\'{compl}\')')
        elif obj == 'all addresses':
            return OrCond(
                f'contain_{obj}(\'{compl}\')' for obj in ['from', 'to', 'bcc', 'to']
            )
    elif verb == 'is greater than' and obj == 'size':
        return LiteralCond(f'is_larger({compl})')
    elif verb == 'is less than' and obj == 'size':
        return LiteralCond(f'is_smaller({compl})')

    # if no return happened earlier throw
    raise ValueError(f'Unimplemented condition transformation "{obj} {verb} {compl}"')


class Cond:
    def __init__(self, conds):
        self.conds = [cond if isinstance(cond, Cond) else LiteralCond(cond) for cond in conds]

    def render(self, base, indent=4):
        if len(self.conds) == 0:
            return '()'
        elif len(self.conds) == 1:
            return self.conds[0].render(base, indent)
        else:
            spaces = ' ' * (indent + 4)
            return '(' + f' {self.sep}\n{spaces}'.join(e.render(base, indent + 4) for e in self.conds) + ')'


class LiteralCond(Cond):
    def __init__(self, filter):
        self.filter = filter

    def render(self, base, indent=0):
        return f'{base}:{self.filter}'


class OrCond(Cond):
    sep = '+'


class AndCond(Cond):
    sep = '*'


def dump_rules(rules, boxes):
    varnames = {}
    script = []
    for servername in boxes:
        varname = make_unique_varname(servername, boxes)
        varnames[servername] = varname
        script.append(
            f'{varname} = IMAP {{'
            f'''
    server = '{servername}',
    username = 'USERNAME',
    password = 'PASSWORD',
    ssl = 'auto'
}}'''
        )

    for _, rule in rules.items():
        try:
            script.append(convert_rule(rule, varnames))
        except ValueError as e:
            log_error(f'WARNING: {e} Ignoring the corresponding rule.')
            continue

    return '\n\n'.join(script)


def make_unique_varname(servername, boxes):
    return '_'.join(
        elem.replace('-', '_') for elem in servername.split('.')[:-1] if elem not in {'imap', 'mail'}
    )


def prefix(elem, bag):
    bag = set(bag)
    bag.discard(elem)
    prefix = ''
    for c in elem:
        if {e for e in bag if e.startswith(prefix)} != set():
            prefix += c
        else:
            return prefix


def norm(s):
    lst = []
    for c in s:
        if c.isalphanum():
            lst.append(c)
        else:
            lst.append('_')
    return ''.join(lst)


def cons(a, gen):
    yield a
    yield from gen


def convert_rule(rule, boxes):
    varname = boxes[rule['box']]
    inbox = f'{varname}.INBOX'
    cond = rule['condition'].render(inbox)
    return '\n'.join(
        f'msgs = {cond}\nmsgs:{convert_action(boxes, action)}' for action in rule['actions']
    )


def convert_action(boxes, action):
    '''
    Convert thunderbird action into imap_filter method call.
    '''

    def noop(_):
        return ''

    def format_folder(action_spec):
        _, (server, address), folder = action_spec
        box = boxes[server]
        return f'{box}[\'{folder}\']'

    functions = {
        'Delete': ('delete_messages()', noop),
        'Move to folder': ('move_messages({})', format_folder),
        'Mark read': ('mark_seen()', noop),
    }

    if action['type'] not in functions:
        raise ValueError(f'Unimplemented action {action["type"]}.')
    else:
        func, formatter = functions[action['type']]

    params = action.get('value', None)

    if params:
        return func.format(formatter(convert_action_params(params)))
    else:
        return func


def log_error(msg):
    print(msg, file=sys.stderr)


if __name__ == '__main__':
    if len(sys.argv) > 1:
        root = os.path.expanduser(sys.argv[1])
        print(main(root))
    else:
        print('Usage: python3 exportFilter.py <Thunderbird profile path>')
