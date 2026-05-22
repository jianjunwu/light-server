"""Custom LitServe loops with adaptive batching for better performance."""

from __future__ import annotations

import time
from queue import Empty, Queue
from typing import Any, Optional

from litserve import LitAPI
from litserve.loops.base import (
    _SENTINEL_VALUE,
    _StopLoopError,
    DefaultLoop,
)
from litserve.loops.simple_loops import BatchedLoop
from litserve.transport.base import MessageTransport
from litserve.utils import LitAPIStatus, LoopResponseType


class AdaptiveBatchedLoop(BatchedLoop):
    """Batched loop with adaptive timeout based on queue depth.

    Strategy:
    - High load: drain the queue immediately; if batch fills up, return at once
    - Medium load: after draining, if queue still has waiting requests,
      wait a short adaptive window (max 2ms) for more to arrive.
    - Low load: single request gets processed immediately with no extra wait.
    """

    def get_batch_requests(
        self,
        lit_api: LitAPI,
        request_queue: Queue,
        transport: MessageTransport,
    ) -> tuple[list, list]:
        payloads: list[tuple[Any, Any, Any]] = []
        timed_out_uids: list[tuple[Any, Any]] = []
        apply_timeout = lit_api.request_timeout not in (-1, False)
        max_batch = lit_api.max_batch_size
        base_timeout = lit_api.batch_timeout

        # Step 1: block for the first request
        first_data = request_queue.get()
        if first_data == _SENTINEL_VALUE:
            raise _StopLoopError()

        response_queue_id, uid, timestamp, x_enc = first_data
        self._send_start(transport, response_queue_id, uid, lit_api)
        if apply_timeout and time.monotonic() - timestamp > lit_api.request_timeout:
            timed_out_uids.append((response_queue_id, uid))
        else:
            payloads.append((response_queue_id, uid, x_enc))

        # Step 2: drain all immediately available requests (non-blocking)
        while len(payloads) < max_batch:
            try:
                request_data = request_queue.get_nowait()
                if request_data == _SENTINEL_VALUE:
                    raise _StopLoopError()
                response_queue_id, uid, timestamp, x_enc = request_data
                self._send_start(transport, response_queue_id, uid, lit_api)
                if apply_timeout and time.monotonic() - timestamp > lit_api.request_timeout:
                    timed_out_uids.append((response_queue_id, uid))
                else:
                    payloads.append((response_queue_id, uid, x_enc))
            except Empty:
                break

        # Step 3: if batch is full, return immediately (high load)
        if len(payloads) >= max_batch:
            return payloads, timed_out_uids

        # Step 4: adaptive wait based on queue depth
        try:
            queue_depth = request_queue.qsize()
        except NotImplementedError:
            queue_depth = 0

        if queue_depth > 0:
            # Medium load: more requests are coming, wait a short time
            adaptive_timeout = min(base_timeout, 0.002)
        elif len(payloads) == 1:
            # Low load: only one request, no point waiting
            adaptive_timeout = 0.0
        else:
            # Partial batch with some requests but queue empty
            adaptive_timeout = min(base_timeout, 0.001)

        if adaptive_timeout > 0:
            end_time = time.monotonic() + adaptive_timeout
            while len(payloads) < max_batch:
                now = time.monotonic()
                remaining = end_time - now
                if remaining <= 0:
                    break
                try:
                    request_data = request_queue.get(timeout=min(remaining, 0.001))
                    if request_data == _SENTINEL_VALUE:
                        raise _StopLoopError()
                    response_queue_id, uid, timestamp, x_enc = request_data
                    self._send_start(transport, response_queue_id, uid, lit_api)
                    if apply_timeout and now - timestamp > lit_api.request_timeout:
                        timed_out_uids.append((response_queue_id, uid))
                    else:
                        payloads.append((response_queue_id, uid, x_enc))
                except Empty:
                    continue

        return payloads, timed_out_uids

    def _send_start(self, transport: MessageTransport, response_queue_id: Any, uid: Any, lit_api: LitAPI) -> None:
        if not self._restart_workers:
            return
        self.put_response(
            transport=transport,
            response_queue_id=response_queue_id,
            uid=uid,
            response_data=(),
            status=LitAPIStatus.START,
            response_type=LoopResponseType.STREAMING if lit_api.stream else LoopResponseType.REGULAR,
        )
