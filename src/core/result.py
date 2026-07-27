from dataclasses import dataclass

# NOTE: Since the old result was archived and is no longer maintained, to follow the Rust pattern of error handling
# I'll use this, since is the minimun and is enough.
# reference: https://github.com/rustedpy/result


@dataclass(frozen=True, slots=True)
class Ok[T]:
    value: T


@dataclass(frozen=True, slots=True)
class Err[E]:
    error: E


type Result[T, E] = Ok[T] | Err[E]
