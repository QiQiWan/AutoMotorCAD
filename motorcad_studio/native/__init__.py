"""Native solver integration boundaries.

The motor domain is solver-independent.  Native packages translate immutable domain
snapshots into versioned solver contracts without allowing Design/UI code to call a
solver API directly.
"""
