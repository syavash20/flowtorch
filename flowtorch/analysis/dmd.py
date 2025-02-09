"""Classes and functions to compute the dynamic mode decomposition (DMD) of a data matrix.
"""

# standard library packages
from typing import Tuple, Set
# third party packages
import torch as pt
from numpy import pi
# flowtorch packages
from .svd import SVD
from flowtorch.data.utils import format_byte_size


class DMD(object):
    """Class computing the exact DMD of a data matrix.

    Currently, no advanced mode selection algorithms are implemented.
    The mode amplitudes are computed using the first snapshot.

    Examples

    >>> from flowtorch import DATASETS
    >>> from flowtorch.data import FOAMDataloader
    >>> from flowtorch.analysis import DMD
    >>> path = DATASETS["of_cavity_binary"]
    >>> loader = FOAMDataloader(path)
    >>> data_matrix = loader.load_snapshot("p", loader.write_times)
    >>> dmd = DMD(data_matrix, dt=0.1, rank=3)
    >>> dmd.frequency
    tensor([0., 5., 0.])
    >>> dmd.growth_rate
    tensor([-2.3842e-06, -4.2345e+01, -1.8552e+01])
    >>> dmd.amplitude
    tensor([10.5635+0.j, -0.0616+0.j, -0.0537+0.j])

    """

    def __init__(self, data_matrix: pt.Tensor, dt: float, rank: int = None):
        """Create DMD instance based on data matrix and time step. 

        :param data_matrix: data matrix whose columns are formed by the individual snapshots
        :type data_matrix: pt.Tensor
        :param dt: time step between two snapshots 
        :type dt: float
        :param rank: rank for SVD truncation, defaults to None
        :type rank: int, optional
        """
        self._dm = data_matrix
        self._dt = dt
        self._svd = SVD(self._dm[:, :-1], rank)
        self._eigvals, self._eigvecs, self._modes = self._compute_mode_decomposition()

    def _compute_mode_decomposition(self):
        """Compute reduced operator, eigen decomposition, and DMD modes.
        """
        s_inv = pt.diag(1.0 / self._svd.s)
        operator = (
            self._svd.U.conj().T @ self._dm[:, 1:] @ self._svd.V @ s_inv
        )
        val, vec = pt.linalg.eig(operator)
        # type conversion is currently not implemented for pt.complex32
        # such that the dtype for the modes is always pt.complex64
        phi = (
            self._dm[:, 1:].type(val.dtype) @ self._svd.V.type(val.dtype)
            @ s_inv.type(val.dtype) @ vec
        )
        return val, vec, phi

    def partial_reconstruction(self, mode_indices: Set[int]) -> pt.Tensor:
        """Reconstruct data matrix with limited number of modes.

        :param mode_indices: mode indices to keep
        :type mode_indices: Set[int]
        :return: reconstructed data matrix
        :rtype: pt.Tensor
        """
        rows, cols = self.modes.shape
        mode_mask = pt.zeros(cols, dtype=pt.complex64)
        mode_indices = pt.tensor(list(mode_indices), dtype=pt.int64)
        mode_mask[mode_indices] = 1.0
        reconstruction = (self.modes * mode_mask) @ self.dynamics
        if self._dm.dtype in (pt.complex64, pt.complex32):
            return reconstruction.type(self._dm.dtype)
        else:
            return reconstruction.real.type(self._dm.dtype)

    @property
    def required_memory(self) -> int:
        """Compute the memory size in bytes of the DMD.

        :return: cumulative size of SVD, eigen values/vectors, and
            DMD modes in bytes
        :rtype: int
        """
        return (self._svd.required_memory +
                self._eigvals.element_size() * self._eigvals.nelement() +
                self._eigvecs.element_size() * self._eigvecs.nelement() +
                self._modes.element_size() * self._modes.nelement())

    @property
    def svd(self) -> SVD:
        return self._svd

    @property
    def modes(self) -> pt.Tensor:
        return self._modes

    @property
    def eigvals(self) -> pt.Tensor:
        return self._eigvals

    @property
    def eigvecs(self) -> pt.Tensor:
        return self._eigvecs

    @property
    def frequency(self) -> pt.Tensor:
        return pt.log(self._eigvals).imag / (2.0 * pi * self._dt)

    @property
    def growth_rate(self) -> pt.Tensor:
        return (pt.log(self._eigvals) / self._dt).real

    @property
    def amplitude(self) -> pt.Tensor:
        return pt.linalg.pinv(self._modes) @ self._dm[:, 0].type(self._modes.dtype)

    @property
    def dynamics(self) -> pt.Tensor:
        return pt.diag(self.amplitude) @ pt.vander(self.eigvals, self._dm.shape[-1], True)

    @property
    def reconstruction(self) -> pt.Tensor:
        """Reconstruct an approximation of the training data.

        :return: reconstructed training data
        :rtype: pt.Tensor
        """
        if self._dm.dtype in (pt.complex64, pt.complex32):
            return (self._modes @ self.dynamics).type(self._dm.dtype)
        else:
            return (self._modes @ self.dynamics).real.type(self._dm.dtype)

    def __repr__(self):
        return f"{self.__class__.__qualname__}(data_matrix, rank={self._svd.rank})"

    def __str__(self):
        ms = ["SVD:", str(self.svd), "LSQ:"]
        size, unit = format_byte_size(self.required_memory)
        ms.append("Overall DMD size: {:1.4f}{:s}".format(size, unit))
        return "\n".join(ms)
