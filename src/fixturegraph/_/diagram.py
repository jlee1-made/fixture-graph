from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, field, dataclass
from typing import Dict, List, Optional, Set, Tuple
import inspect
import re
import subprocess
import tempfile
import typing


def filter_out_synonymous_attributes(synonymous_attrs, entity, attrs):
    seen = {}
    filtered = []
    for k, v in attrs:
        synonyms = synonymous_attrs.get(type(entity), [])
        if k in synonyms:
            representative = synonyms[0]
            if representative in seen:
                continue
            else:
                seen[representative] = True
        filtered.append((k, v))
    return filtered


def is_sequence_of_strings(value):
    return not isinstance(value, str) and isinstance(value, Sequence) and all(
        isinstance(x, str) for x in value)


def isnamedtupleinstance(x):
    t = type(x)
    b = t.__bases__
    if len(b) != 1 or b[0] != tuple:
        return False
    f = getattr(t, '_fields', None)
    if not isinstance(f, tuple):
        return False
    return all(type(n) == str for n in f)


def get_attrs(synonymous_attrs, entity):
    attrs = {}
    is_namedtuple = isnamedtupleinstance(entity)
    for k, v in inspect.getmembers(entity, lambda a: not inspect.isroutine(a)):
        if k.startswith("__"):
            continue
        if is_namedtuple and k == "_fields":
            continue

        if isinstance(v, str):
            attrs[k.lstrip("_")] = v
        if is_sequence_of_strings(v):
            base = k.lstrip("_")
            for i, item in enumerate(v):
                attrs[f"{base}_{i}"] = item
    return filter_out_synonymous_attributes(synonymous_attrs, entity, attrs.items())


def get_children(attrs, entity):
    attr_names = attrs.get(type(entity), [])
    for name in attr_names:
        value = getattr(entity, name)
        if isinstance(value, list):
            for i, v in enumerate(value):
                yield f"{name}_{i}", v
        else:
            yield name, value


def entity_name(id_attrs, entity):
    type_ = type(entity)
    attr = getattr(entity, id_attrs[type_])
    if callable(attr):
        value = attr()
    else:
        value = attr
    if isinstance(value, tuple):
        value = "_".join(value)
    return str(type_.__name__) + "_" + value


class Node(typing.NamedTuple):
    name: str


@dataclass(order=True, eq=True, frozen=True)
class Arrow:
    src_name: str
    dst_name: str
    key: str
    value: Optional[str]
    guessed: bool
    src_type: type
    dst_type: type

    def __post_init__(self):
        assert self.guessed == (self.value is not None), (self.guessed, self.value)

    def __str__(self):
        if self.value is not None:
            return (
                "{src_name} ({src_type.__name__}) -> {dst_name} ({dst_type.__name__}) "  # noqa
                "on attr {key} matched on {value}").format(**asdict(self))
        else:
            return (
                "{src_name} ({src_type.__name__}) -> {dst_name} ({dst_type.__name__}) "  # noqa
                "on attr {key}").format(**asdict(self))


class DotArrow(typing.NamedTuple):
    src: str
    dst: str
    label: Optional[str]
    bidirectional: bool

    @classmethod
    def make(cls, *, src, dst, label, bidirectional):
        # This is for reproducibility of how dot draws the graph: Strictly it
        # shouldn't matter which way round the nodes are listed when it's a
        # bidirectional edge, because it's the same edge mathematically
        # regardless of that order.  dot draws the graph differently depending
        # on the order though, so make it consistent across runs by sorting.
        if bidirectional:
            src, dst = sorted([src, dst])
        return DotArrow(src=src, dst=dst, label=label, bidirectional=bidirectional)


def write_dot(fh, lines):
    fh.write("digraph graphname{\n")
    for line in lines:
        fh.write(line + "\n")
    fh.write("}\n")


def slugify(s):
    s = s.lower()
    for c in [" ", "-", ".", "/"]:
        s = s.replace(c, "_")
    s = re.sub(r"\W", "", s)
    s = s.replace("_", " ")
    s = re.sub(r"\s+", " ", s)
    s = s.strip()
    return s.replace(" ", "_")


@dataclass
class Configuration:
    id_attrs: Dict[type, str]
    attrs_with_child_refs: Dict[type, List[str]] = field(default_factory=dict)
    synonymous_attrs: Dict[type, List[str]] = field(default_factory=dict)


def make_guessed_arrows_from_attr_string_values(config, entities) -> List[Arrow]:
    attrs_by_entity_name = {}
    types_by_entity_name = {}
    by_value: Dict[str, Set[str]] = {}
    for entity in entities:
        name = entity_name(config.id_attrs, entity)
        attrs = get_attrs(config.synonymous_attrs, entity)
        attrs_by_entity_name[name] = attrs
        types_by_entity_name[name] = type(entity)
        for k, v in attrs:
            by_value.setdefault(v, set()).add(name)

    attrs_: Dict[Tuple[type, str, type, str], Set[Tuple[str, str]]] = {}
    for src_name, src_attrs in attrs_by_entity_name.items():
        src_type = types_by_entity_name[src_name]
        for k, v in src_attrs:
            dst_names = set(by_value.get(v, []))
            dst_names.discard(src_name)
            for dst_name in dst_names:
                dst_type = types_by_entity_name[dst_name]
                attrs_.setdefault((src_type, src_name, dst_type, dst_name), set()).add(
                    (k, v))

    arrows = []
    for (src_type, src_name, dst_type, dst_name), attrs in attrs_.items():
        for k, v in attrs:
            arrows.append(
                Arrow(
                    src_type=src_type,
                    src_name=slugify(src_name),
                    dst_type=dst_type,
                    dst_name=slugify(dst_name),
                    key=k,
                    value=v,
                    guessed=True,
                ))

    return arrows


def make_arrows_from_python_refs(config, entities) -> List[Arrow]:
    arrows = []
    for entity in entities:
        for attr_name, child in get_children(config.attrs_with_child_refs, entity):
            parent_name = entity_name(config.id_attrs, entity)
            child_name = entity_name(config.id_attrs, child)
            arrows.append(
                Arrow(
                    src_type=type(entity),
                    src_name=slugify(parent_name),
                    dst_type=type(child),
                    dst_name=slugify(child_name),
                    key=attr_name,
                    value=None,
                    guessed=False,
                ))
    return arrows


class Index:

    def __init__(
        self,
        *,
        by_src_dst_name_pairs,
        by_undirected_src_dst_name_pairs,
    ):
        self._by_src_dst_name_pairs = by_src_dst_name_pairs
        self._by_undirected_src_dst_name_pairs = by_undirected_src_dst_name_pairs

    def grouped_by_undirected_edge_and_value(self, arrows):
        ungrouped = set(arrows)
        groups = []
        for names, group in self._by_undirected_src_dst_name_pairs.items():
            matching = group & ungrouped
            ungrouped -= matching
            if len(matching) != 0:
                groups.append((names, matching))
        return groups, ungrouped

    def grouped_by_directed_edge(self, arrows):
        for names, group in self._by_src_dst_name_pairs.items():
            matching = group & arrows
            if len(matching) != 0:
                yield names, matching


def make_index(arrows: List[Arrow]) -> Index:
    by_src_dst_name_pairs = defaultdict(set)
    by_undirected_src_dst_name_pairs = defaultdict(set)
    for a in arrows:
        by_src_dst_name_pairs[(a.src_name, a.dst_name)].add(a)
        by_undirected_src_dst_name_pairs[frozenset([a.src_name, a.dst_name])].add(a)
    return Index(by_src_dst_name_pairs=by_src_dst_name_pairs,
                 by_undirected_src_dst_name_pairs=by_undirected_src_dst_name_pairs)


def combine_arrows(rules, arrows_: List[Arrow]) -> List[DotArrow]:
    index = make_index(arrows_)
    r = []

    def make_label(arrows):
        keys = set(a.key for a in arrows)
        return "<br/>".join(slugify(k) for k in sorted(keys))

    arrows = set(arrows_)

    guessed = set(a for a in arrows if a.guessed)
    not_guessed = arrows - guessed

    # Combine arrows that were guessed based on values, where they share the
    # same value.
    groups, arrows = index.grouped_by_undirected_edge_and_value(guessed)
    for (name1, name2), group in groups:
        label = make_label(group)
        r.append(DotArrow.make(src=name1, dst=name2, label=label, bidirectional=True))

    arrows |= not_guessed

    # Combine remaining arrows if they share a directed edge.
    for (src_name, dst_name), group in index.grouped_by_directed_edge(arrows):
        label = make_label(group)
        r.append(
            DotArrow.make(src=src_name, dst=dst_name, label=label, bidirectional=False))

    return r


def make_arrows(config, entities) -> List[Arrow]:
    arrows = []
    arrows.extend(make_guessed_arrows_from_attr_string_values(config, entities))
    arrows.extend(make_arrows_from_python_refs(config, entities))
    return arrows


def render_to_dot(nodes: List[Node], arrows: List[DotArrow]) -> List[str]:
    node_names = set()
    for node in nodes:
        node_names.add(node.name)
    dot = []
    for name in sorted(node_names):
        dot.append(name)
    for arrow in sorted(arrows):
        if arrow.label is None:
            if arrow.bidirectional:
                dot.append(f'{arrow.src}->{arrow.dst} [ dir="both"]')
            else:
                dot.append(f"{arrow.src}->{arrow.dst}")
        else:
            if arrow.bidirectional:
                dot.append(
                    f'{arrow.src}->{arrow.dst} [ label= <{arrow.label}> dir="both" ]')
            else:
                dot.append(f"{arrow.src}->{arrow.dst} [ label= <{arrow.label}> ]")
    return dot


def make_rules(config):
    # I was thinking here it might be useful to explicitly represent and make
    # configurable the rules used to combine Arrows into DotArrows
    pass


def make_nodes(config, entities):
    return [Node(slugify(entity_name(config.id_attrs, entity))) for entity in entities]


def diagram(config, entities):
    arrows = make_arrows(config, entities)
    rules = make_rules(config)
    dot_arrows = combine_arrows(rules, arrows)
    nodes = make_nodes(config, entities)
    return render_to_dot(nodes, dot_arrows)


def show_diagram(config: Configuration, entities: List[object]):
    dot = diagram(config, entities)
    if len(dot) == 0:
        print("Found no relations, not showing dot graph")
        return

    path = tempfile.mktemp(suffix=".dot")
    with open(path, "w") as fh:
        write_dot(fh, dot)
    child = subprocess.run(["bash", "-c", f"dot -Tsvg {path} | display"],
                           capture_output=True)
    if child.returncode != 0:
        print("Failed to run dot with this input file content:")
        print("\n".join(dot))
        print("dot stdout:")
        print(child.stdout)
        print("dot stderr:")
        print(child.stderr)
