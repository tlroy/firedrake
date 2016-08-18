from firedrake import *
import pytest
import numpy as np


@pytest.fixture
def mesh():
    return UnitSquareMesh(4, 4)


@pytest.fixture(params=["scalar", "vector"])
def V(mesh, request):
    if request.param == "scalar":
        return FunctionSpace(mesh, "CG", 1)
    elif request.param == "vector":
        return VectorFunctionSpace(mesh, "CG", 1)


@pytest.fixture
def L(V):
    x = SpatialCoordinate(V.mesh())
    v = TestFunction(V)
    if V.shape == ():
        return sin(x[0]*2*pi)*sin(x[1]*2*pi)*v*dx
    elif V.shape == (2, ):
        return inner(as_vector([sin(x[0]*2*pi)*sin(x[1]*2*pi),
                                cos(x[0]*2*pi)*cos(x[1]*2*pi) - 1]),
                     v)*dx


@pytest.fixture(params=["Poisson", "Mass"])
def problem(request):
    return request.param


@pytest.fixture
def a(problem, V):
    u = TrialFunction(V)
    v = TestFunction(V)
    if problem == "Poisson":
        return inner(grad(u), grad(v))*dx
    elif problem == "Mass":
        return inner(u, v)*dx


@pytest.fixture
def bcs(problem, V):
    if problem == "Poisson":
        return DirichletBC(V, zero(V.shape), (1, 2, 3, 4))
    elif problem == "Mass":
        return None


@pytest.mark.parametrize("pc_type", ("none",
                                     "ilu",
                                     "lu"))
def test_assembled_pc_equivalence(V, a, L, bcs, tmpdir, pc_type):

    u = Function(V)

    assembled = str("assembled")
    matrixfree = str("matrixfree")

    assembled_parameters = {"ksp_type": "cg",
                            "pc_type": pc_type,
                            "ksp_monitor_short": "ascii:%s:" % assembled}
    u.assign(0)
    solve(a == L, u, bcs=bcs, solver_parameters=assembled_parameters)

    matrixfree_parameters = {"mat_type": "matfree",
                             "ksp_type": "cg",
                             "pc_type": "python",
                             "pc_python_type": "firedrake.AssembledPC",
                             "assembled_pc_type": pc_type,
                             "ksp_monitor_short": "ascii:%s:" % matrixfree,
                             "options_left": True}

    u.assign(0)
    solve(a == L, u, bcs=bcs, solver_parameters=matrixfree_parameters)

    with open(assembled, "r") as f:
        f.readline()            # Skip over header
        expect = f.read()

    with open(matrixfree, "r") as f:
        f.readline()            # Skip over header
        actual = f.read()

    assert expect == actual


@pytest.mark.parametrize("bcs", [False, True],
                         ids=["no bcs", "bcs"])
def test_matrixfree_action(a, V, bcs):
    f = Function(V)
    expect = Function(V)
    actual = Function(V)

    x = SpatialCoordinate(V.mesh())
    if V.shape == ():
        f.interpolate(x[0]*sin(x[1]*2*pi))
    elif V.shape == (2, ):
        f.interpolate(as_vector([x[0]*sin(x[1]*2*pi),
                                 x[1]*cos(x[0]*2*pi)]))

    if bcs:
        bcs = DirichletBC(V, zero(V.shape), (1, 2))
    else:
        bcs = None
    A = assemble(a, bcs=bcs)
    A.force_evaluation()
    Amf = assemble(a, mat_type="matfree", bcs=bcs)
    Amf.force_evaluation()

    with f.dat.vec_ro as x:
        with expect.dat.vec as y:
            A.petscmat.mult(x, y)
        with actual.dat.vec as y:
            Amf.petscmat.mult(x, y)

    assert np.allclose(expect.dat.data_ro, actual.dat.data_ro)


@pytest.mark.parametrize("preassembled", [False, True],
                         ids=["variational", "preassembled"])
@pytest.mark.parametrize("parameters",
                         [{"ksp_type": "preonly",
                           "pc_type": "python",
                           "pc_python_type": "firedrake.AssembledPC",
                           "assembled_pc_type": "lu"},
                          {"ksp_type": "preonly",
                           "pc_type": "fieldsplit",
                           "pc_fieldsplit_type": "additive",
                           "fieldsplit_pc_type": "python",
                           "fieldsplit_pc_python_type": "firedrake.AssembledPC",
                           "fieldsplit_assembled_pc_type": "lu"},
                          {"ksp_type": "preonly",
                           "pc_type": "fieldsplit",
                           "pc_fieldsplit_type": "additive",
                           "pc_fieldsplit_0_fields": "1",
                           "pc_fieldsplit_1_fields": "0,2",
                           "fieldsplit_0_pc_type": "python",
                           "fieldsplit_0_pc_python_type": "firedrake.MassInvPC",
                           "fieldsplit_0_Mp_pc_type": "lu",
                           "fieldsplit_1_pc_type": "python",
                           "fieldsplit_1_pc_python_type": "firedrake.AssembledPC",
                           "fieldsplit_1_assembled_pc_type": "lu"},
                          {"ksp_type": "preonly",
                           "pc_type": "fieldsplit",
                           "pc_fieldsplit_type": "additive",
                           "pc_fieldsplit_0_fields": "1",
                           "pc_fieldsplit_1_fields": "0,2",
                           "fieldsplit_0_pc_type": "python",
                           "fieldsplit_0_pc_python_type": "firedrake.MassInvPC",
                           "fieldsplit_0_Mp_pc_type": "lu",
                           "fieldsplit_1_pc_type": "fieldsplit",
                           "fieldsplit_1_pc_fieldsplit_type": "additive",
                           "fieldsplit_1_fieldsplit_0_pc_type": "python",
                           "fieldsplit_1_fieldsplit_0_pc_python_type": "firedrake.MassInvPC",
                           "fieldsplit_1_fieldsplit_0_Mp_pc_type": "lu",
                           "fieldsplit_1_fieldsplit_1_pc_type": "python",
                           "fieldsplit_1_fieldsplit_1_pc_python_type": "firedrake.AssembledPC",
                           "fieldsplit_1_fieldsplit_1_assembled_pc_type": "lu"}])
def test_fieldsplitting(mesh, preassembled, parameters):
    V = FunctionSpace(mesh, "CG", 1)
    P = FunctionSpace(mesh, "DG", 0)
    Q = VectorFunctionSpace(mesh, "DG", 1)
    W = V*P*Q

    expect = Constant((1, 2, 3, 4))

    u = TrialFunction(W)
    v = TestFunction(W)

    a = inner(u, v)*dx

    L = inner(expect, v)*dx

    f = Function(W)

    if preassembled:
        A = assemble(a, mat_type="matfree")
        b = assemble(L)
        solve(A, f, b, solver_parameters=parameters)
    else:
        parameters["mat_type"] = "matfree"
        solve(a == L, f, solver_parameters=parameters)

    f -= expect

    for d in f.dat.data_ro:
        assert np.allclose(d, 0.0)
