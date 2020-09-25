from typing import NamedTuple

from dataclasses import dataclass
import fixturegraph
from fixturegraph._.diagram import Arrow, combine_arrows, diagram, make_arrows


@dataclass
class Widget:
    ref: str
    lozenge: str
    part: str


@dataclass
class Lozenge:
    ref: str
    widget: str


class Parent:

    def __init__(self, reference, children, pyref=None, matching=None, matching2=None):
        self.reference = reference
        self.children = children
        self.pyref = pyref
        self.matching = matching
        self.matching2 = matching2


class Child:

    def __init__(self, id, matching=None):
        self.id = id
        self.matching = matching


def test_inferring_arrows():
    w1 = Widget(ref="1", lozenge="1", part="1")
    l1 = Lozenge(ref="1", widget="1")
    entities = [w1, l1]
    config = fixturegraph.Configuration(id_attrs={
        Widget: "ref",
        Lozenge: "ref",
    }, )
    arrows = make_arrows(config, entities)
    assert list(map(str, sorted(arrows))) == [
        'lozenge_1 (Lozenge) -> widget_1 (Widget) on attr ref matched on 1',
        'lozenge_1 (Lozenge) -> widget_1 (Widget) on attr widget matched on 1',
        'widget_1 (Widget) -> lozenge_1 (Lozenge) on attr lozenge matched on 1',
        'widget_1 (Widget) -> lozenge_1 (Lozenge) on attr part matched on 1',
        'widget_1 (Widget) -> lozenge_1 (Lozenge) on attr ref matched on 1',
    ]


def test_combining_inferred_arrows():
    # Note though the ids are all the same here, the ids on Widget and Lozenge
    # are distinguished for purposes of combining arrows because Widget and
    # Lozenge are different types and have different class names.  However, for
    # purposes of inferring arrows, they are the same value.
    w1 = Widget(ref="1", lozenge="1", part="1")
    l1 = Lozenge(ref="1", widget="1")
    entities = [w1, l1]
    config = fixturegraph.Configuration(id_attrs={
        Widget: "ref",
        Lozenge: "ref",
    }, )

    arrows = combine_arrows("dummy", make_arrows(config, entities))
    assert list(map(str, sorted(arrows))) == [
        "DotArrow(src='lozenge_1', dst='widget_1', "
        "label='lozenge<br/>part<br/>ref<br/>widget', bidirectional=True)",
    ]

    dot = diagram(config, entities)
    assert dot == [
        'Lozenge_1',
        'Widget_1',
        'lozenge_1->widget_1 [ label= <lozenge<br/>part<br/>ref<br/>widget> dir="both" ]',
    ]


def test_combining_inferred_together_with_parent_child_arrows():
    child1 = Child("child1", matching="spam")
    child2 = Child("child2", matching="ham")
    parent = Parent("ref", [child1, child2], matching="spam")
    entities = [parent, child1, child2]
    config = fixturegraph.Configuration(
        id_attrs={
            Parent: "reference",
            Child: "id",
        },
        attrs_with_child_refs={
            Parent: ["children"],
        },
    )
    dot = diagram(config, entities)
    assert dot == [
        'Child_child1',
        'Child_child2',
        'Parent_ref',
        'child_child1->parent_ref [ label= <matching> dir="both" ]',
        'parent_ref->child_child1 [ label= <children_0> ]',
        'parent_ref->child_child2 [ label= <children_1> ]',
    ]


def test_combining_multiple_inferred_together_with_parent_child_arrows():
    # Multiple inferred arrows between same two nodes
    child1 = Child("child1", matching="spam")
    child2 = Child("child2", matching="ham")
    parent = Parent("ref", [child1, child2], matching="spam", matching2="spam")
    entities = [parent, child1, child2]
    config = fixturegraph.Configuration(
        id_attrs={
            Parent: "reference",
            Child: "id",
        },
        attrs_with_child_refs={
            Parent: ["children"],
        },
    )
    dot = diagram(config, entities)
    assert dot == [
        'Child_child1',
        'Child_child2',
        'Parent_ref',
        'child_child1->parent_ref [ label= <matching<br/>matching2> dir="both" ]',
        'parent_ref->child_child1 [ label= <children_0> ]',
        'parent_ref->child_child2 [ label= <children_1> ]',
    ]


def test_nodes_with_no_relationship_still_show_up_as_nodes():
    child1 = Child("child1")
    child2 = Child("child2")
    parent = Parent("ref", [child1, child2])
    entities = [parent, child1, child2]
    # no configuration to tell fixturegraph about explicit parent-child
    # attribute relationship here, so it doesn't notice that there is any
    # relationship at all
    config = fixturegraph.Configuration(id_attrs={
        Parent: "reference",
        Child: "id",
    }, )
    dot = diagram(config, entities)
    assert dot == [
        'Child_child1',
        'Child_child2',
        'Parent_ref',
    ]


def test_explicit_parent_child_relationship():
    child1 = Child("child1")
    child2 = Child("child2")
    parent = Parent("ref", [child1, child2])
    entities = [parent, child1, child2]
    config = fixturegraph.Configuration(
        id_attrs={
            Parent: "reference",
            Child: "id",
        },
        attrs_with_child_refs={
            Parent: ["children"],
        },
    )
    dot = diagram(config, entities)
    assert dot == [
        'Child_child1',
        'Child_child2',
        'Parent_ref',
        'parent_ref->child_child1 [ label= <children_0> ]',
        'parent_ref->child_child2 [ label= <children_1> ]',
    ]


def test_combining_arrows_from_parent_child_relationship():
    child1 = Child("child1")
    child2 = Child("child2")
    parent = Parent("ref", [child1, child2], pyref=child1)
    entities = [parent, child1, child2]
    config = fixturegraph.Configuration(
        id_attrs={
            Parent: "reference",
            Child: "id",
        },
        attrs_with_child_refs={
            Parent: ["children", "pyref"],
        },
    )
    dot = diagram(config, entities)
    # This tests combining arrows using the second rule of combining arrows:
    # arrows left over after combining into bidirectional arrows are combined
    # based on sharing directed node pair.
    assert dot == [
        'Child_child1',
        'Child_child2',
        'Parent_ref',
        'parent_ref->child_child1 [ label= <children_0<br/>pyref> ]',
        'parent_ref->child_child2 [ label= <children_1> ]',
    ]


def test_readme_example():

    class SaleOrder(NamedTuple):
        reference: str
        sku: str

    class Product(NamedTuple):
        sku: str

    entities = [SaleOrder(reference="123", sku="abc"), Product(sku="abc")]
    config = fixturegraph.Configuration(id_attrs={
        SaleOrder: "reference",
        Product: "sku",
    }, )
    # fixturegraph.show_diagram(config, entities)
    dot = diagram(config, entities)
    assert dot == [
        'product_abc',
        'saleorder_123',
        'product_abc->saleorder_123 [ label= <sku> dir="both" ]',
    ]
