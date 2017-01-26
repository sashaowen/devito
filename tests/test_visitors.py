import pytest

import cgen as c
from sympy import Eq

from devito.dimension import Dimension
from devito.interfaces import DenseData
from devito.nodes import Block, Expression, Iteration
from devito.visitors import FindSections, IsPerfectIteration, Transformer


def _symbol(name, dimensions):
    return DenseData(name=name, dimensions=dimensions).indexify()


@pytest.fixture(scope="session")
def exprs():
    i = Dimension(name='i', size=3)
    a = _symbol(name='a', dimensions=(i,))
    b = _symbol(name='b', dimensions=(i,))
    return [Expression(Eq(a, a + b + 5.)),
            Expression(Eq(a, b - a)),
            Expression(Eq(a, 4 * (b * a))),
            Expression(Eq(a, (6. / b) + (8. * a)))]


@pytest.fixture(scope="session")
def iters():
    return [lambda ex: Iteration(ex, Dimension('i', size=3), (0, 3, 1)),
            lambda ex: Iteration(ex, Dimension('j', size=5), (0, 5, 1)),
            lambda ex: Iteration(ex, Dimension('k', size=7), (0, 7, 1)),
            lambda ex: Iteration(ex, Dimension('s', size=4), (0, 4, 1)),
            lambda ex: Iteration(ex, Dimension('p', size=4), (0, 4, 1))]


@pytest.fixture(scope="session")
def block1(exprs, iters):
    # Perfect loop nest:
    # for i
    #   for j
    #     for k
    #       expr0
    return iters[0](iters[1](iters[2](exprs[0])))


@pytest.fixture(scope="session")
def block2(exprs, iters):
    # Non-perfect simple loop nest:
    # for i
    #   expr0
    #   for j
    #     for k
    #       expr1
    return iters[0]([exprs[0], iters[1](iters[2](exprs[1]))])


@pytest.fixture(scope="session")
def block3(exprs, iters):
    # Non-perfect non-trivial loop nest:
    # for i
    #   for s
    #     expr0
    #   for j
    #     for k
    #       expr1
    #       expr2
    #   for p
    #     expr3
    return iters[0]([iters[3](exprs[0]),
                     iters[1](iters[2]([exprs[1], exprs[2]])),
                     iters[4](exprs[3])])


def test_find_sections(exprs, block1, block2, block3):
    finder = FindSections()

    sections = finder.visit(block1)
    assert len(sections) == 1

    sections = finder.visit(block2)
    assert len(sections) == 2
    found = list(sections.values())
    assert len(found[0]) == 1
    assert found[0][0].stencil == exprs[0].stencil
    assert len(found[1]) == 1
    assert found[1][0].stencil == exprs[1].stencil

    sections = finder.visit(block3)
    assert len(sections) == 3
    found = list(sections.values())
    assert len(found[0]) == 1
    assert found[0][0].stencil == exprs[0].stencil
    assert len(found[1]) == 2
    assert found[1][0].stencil == exprs[1].stencil
    assert found[1][1].stencil == exprs[2].stencil
    assert len(found[2]) == 1
    assert found[2][0].stencil == exprs[3].stencil


def test_is_perfect_iteration(block1, block2, block3):
    checker = IsPerfectIteration()

    assert checker.visit(block1) is True
    assert checker.visit(block1.nodes[0]) is True
    assert checker.visit(block1.nodes[0].nodes[0]) is True

    assert checker.visit(block2) is False
    assert checker.visit(block2.nodes[1]) is True
    assert checker.visit(block2.nodes[1].nodes[0]) is True

    assert checker.visit(block3) is False
    assert checker.visit(block3.nodes[0]) is True
    assert checker.visit(block3.nodes[1]) is True
    assert checker.visit(block3.nodes[2]) is True


def test_transformer_wrap(exprs, block1, block2, block3):
    """Basic transformer test that wraps an expression in comments"""
    line1 = '// This is the opening comment'
    line2 = '// This is the closing comment'
    wrapper = lambda n: Block(c.Line(line1), n, c.Line(line2))
    transformer = Transformer({exprs[0]: wrapper(exprs[0])})

    for block in [block1, block2, block3]:
        newblock = transformer.visit(block)
        newcode = str(newblock.ccode)
        oldnumlines = len(str(block.ccode).split('\n'))
        newnumlines = len(newcode.split('\n'))
        assert newnumlines >= oldnumlines + 2
        assert line1 in newcode
        assert line2 in newcode
        assert "a[i] = a[i] + b[i] + 5.0F;" in newcode


def test_transformer_replace(exprs, block1, block2, block3):
    """Basic transformer test that replaces an expression"""
    line1 = '// Replaced expression'
    replacer = Block(c.Line(line1))
    transformer = Transformer({exprs[0]: replacer})

    for block in [block1, block2, block3]:
        newblock = transformer.visit(block)
        newcode = str(newblock.ccode)
        oldnumlines = len(str(block.ccode).split('\n'))
        newnumlines = len(newcode.split('\n'))
        assert newnumlines >= oldnumlines
        assert line1 in newcode
        assert "a[i0] = a[i0] + b[i0] + 5.0F;" not in newcode


def test_transformer_add_replace(exprs, block2, block3):
    """Basic transformer test that adds one expression and replaces another"""
    line1 = '// Replaced expression'
    line2 = '// Adding a simple line'
    replacer = Block(c.Line(line1))
    adder = lambda n: Block(c.Line(line2), n)
    transformer = Transformer({exprs[0]: replacer,
                               exprs[1]: adder(exprs[1])})

    for block in [block2, block3]:
        newblock = transformer.visit(block)
        newcode = str(newblock.ccode)
        oldnumlines = len(str(block.ccode).split('\n'))
        newnumlines = len(newcode.split('\n'))
        assert newnumlines >= oldnumlines + 1
        assert line1 in newcode
        assert line2 in newcode
        assert "a[i0] = a[i0] + b[i0] + 5.0F;" not in newcode
