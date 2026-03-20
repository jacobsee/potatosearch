"""
Subprocess worker for FAISS IVF-PQ training.

Runs in a separate process that does NOT load PyTorch, allowing FAISS to
use multi-threaded OMP without conflicting & causing a dual-libomp segfault.

Protocol:
  argv[1]  - path to .npy file with training vectors (n, dim) float32
  argv[2]  - path to write the trained index
  argv[3]  - nlist  (int)
  argv[4]  - pq_m   (int)
  argv[5]  - dimension (int)

Exit code 0 on success; non-zero on failure (stderr has the traceback).
"""
import os
import sys


def main() -> None:
    # Let FAISS use all available cores - no PyTorch in this process.
    os.environ.pop("OMP_NUM_THREADS", None)
    os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

    import numpy as np
    import faiss

    vectors_path, index_path = sys.argv[1], sys.argv[2]
    nlist, pq_m, dim = int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])

    n_threads = os.cpu_count() or 1
    faiss.omp_set_num_threads(n_threads)

    train_vectors = np.load(vectors_path)
    assert train_vectors.shape[1] == dim

    faiss.normalize_L2(train_vectors)

    quantizer = faiss.IndexFlatIP(dim)
    index = faiss.IndexIVFPQ(
        quantizer, dim, nlist, pq_m, 8, faiss.METRIC_INNER_PRODUCT,
    )

    print(
        f"Training IVF-PQ (nlist={nlist}, pq_m={pq_m}, "
        f"samples={len(train_vectors)}, threads={n_threads})",
        flush=True,
    )
    index.train(train_vectors)
    print("Training complete.", flush=True)

    faiss.write_index(index, index_path)


if __name__ == "__main__":
    main()
