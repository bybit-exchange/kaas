"""Pipeline package -- modular pipeline architecture.

Re-exports the public API so that:
    from kb_ai.commands.pipeline import run_server_pipeline_with_input
continues to work.
"""

from kb_ai.commands.pipeline._entry import (  # noqa: F401
    run_server_pipeline,
    run_server_pipeline_with_input,
    run_server_index,
    run_server_index_with_input,
)
