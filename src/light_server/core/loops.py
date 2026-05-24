"""Custom LitServe loops with adaptive batching and bidirectional streaming."""

from __future__ import annotations

import logging
import threading
import time
from queue import Empty, Queue
from typing import Any, Optional

from litserve import LitAPI
from litserve.callbacks import CallbackRunner, EventTypes
from litserve.loops.base import (
    _SENTINEL_VALUE,
    _StopLoopError,
    DefaultLoop,
    _inject_context,
)
from litserve.loops.simple_loops import BatchedLoop
from litserve.transport.base import MessageTransport
from litserve.utils import LitAPIStatus, LoopResponseType

logger = logging.getLogger(__name__)


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
        apply_timeout = lit_api.request_timeout is not None and lit_api.request_timeout not in (-1, False)
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

        # Zero-copy: restore payloads that were offloaded to shared memory
        converted: list[tuple[Any, Any, Any]] = []
        for response_queue_id, uid, x_enc in payloads:
            if isinstance(x_enc, tuple) and len(x_enc) == 2 and x_enc[0] in ("direct", "shm"):
                from light_server.core.shm_buffer import ShmPayloadBuffer
                x_enc = ShmPayloadBuffer.retrieve(x_enc[0], x_enc[1])
            converted.append((response_queue_id, uid, x_enc))
        return converted, timed_out_uids

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


class StreamSession:
    """Manages a single bidirectional stream in a worker process."""

    def __init__(
        self,
        stream_id: str,
        lit_api: LitAPI,
        transport: MessageTransport,
        response_queue_id: int,
        loop_instance: "BidirectionalStreamingLoop",
    ) -> None:
        self.stream_id = stream_id
        self.lit_api = lit_api
        self.transport = transport
        self.response_queue_id = response_queue_id
        self.loop_instance = loop_instance
        self.input_queue: Queue = Queue()
        self.closed = False
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, daemon=True, name=f"stream-session-{self.stream_id}")
        self.thread.start()

    def push_chunk(self, chunk: dict[str, Any]) -> None:
        self.input_queue.put(chunk)

    def close(self) -> None:
        self.closed = True
        self.input_queue.put(None)  # EOF marker

    def cancel(self) -> None:
        self.closed = True
        # Drain remaining chunks to unblock the generator
        while not self.input_queue.empty():
            try:
                self.input_queue.get_nowait()
            except Empty:
                break
        self.input_queue.put(None)

    def _run(self) -> None:
        try:
            def input_gen():
                while True:
                    chunk = self.input_queue.get()
                    if chunk is None:
                        break
                    yield chunk

            # Prefer stream_predict if the model implements it
            if hasattr(self.lit_api, "stream_predict") and callable(getattr(self.lit_api, "stream_predict")):
                output_gen = self.lit_api.stream_predict(input_gen())
            else:
                output_gen = self._fallback_predict(input_gen())

            for output in output_gen:
                y_enc = self.lit_api.encode_response(output)
                y_enc = self.lit_api.format_encoded_response(y_enc)
                self.loop_instance.put_response(
                    self.transport,
                    self.response_queue_id,
                    self.stream_id,
                    y_enc,
                    LitAPIStatus.OK,
                    LoopResponseType.STREAMING,
                )

            if not self.closed:
                self.loop_instance.put_response(
                    self.transport,
                    self.response_queue_id,
                    self.stream_id,
                    "",
                    LitAPIStatus.FINISH_STREAMING,
                    LoopResponseType.STREAMING,
                )
        except Exception as e:
            logger.exception(f"StreamSession {self.stream_id} error: {e}")
            self.loop_instance.put_error_response(
                self.transport,
                self.response_queue_id,
                self.stream_id,
                e,
                LoopResponseType.STREAMING,
            )

    def _fallback_predict(self, input_gen):
        for chunk in input_gen:
            result = self.lit_api.predict(chunk)
            if hasattr(result, "__iter__") and not isinstance(result, (str, bytes, dict, list, tuple)):
                yield from result
            else:
                yield result


class BidirectionalStreamingLoop(DefaultLoop):
    """Worker loop that supports bidirectional streaming input + output.

    - Regular requests (no _stream_meta) are processed as one-shot streaming
      responses (same as StreamingLoop).
    - Stream messages (_stream_meta present) are routed to StreamSessions
      that run in background threads, enabling concurrent stream handling.
    """

    def __init__(self) -> None:
        super().__init__()
        self.sessions: dict[str, StreamSession] = {}
        self._session_lock = threading.Lock()

    def __call__(
        self,
        lit_api: LitAPI,
        device: str,
        worker_id: int,
        request_queue: Queue,
        transport: MessageTransport,
        workers_setup_status: dict[int, str],
        callback_runner: CallbackRunner,
    ) -> None:
        self.run_bidirectional_loop(lit_api, request_queue, transport, callback_runner)

    def run_bidirectional_loop(
        self,
        lit_api: LitAPI,
        request_queue: Queue,
        transport: MessageTransport,
        callback_runner: CallbackRunner,
    ) -> None:
        while True:
            try:
                request_data = request_queue.get(timeout=1.0)
                if request_data == _SENTINEL_VALUE:
                    return

                response_queue_id, uid, timestamp, payload = request_data

                # Detect bidirectional stream messages
                if isinstance(payload, dict) and "_stream_meta" in payload:
                    self._handle_stream_message(
                        payload, response_queue_id, uid, lit_api, transport, callback_runner
                    )
                    continue

                # Regular one-shot streaming request
                self._process_request(
                    response_queue_id, uid, timestamp, payload, lit_api, transport, callback_runner
                )

            except (Empty, ValueError):
                continue
            except KeyboardInterrupt:
                self.kill()
                return

    def _handle_stream_message(
        self,
        payload: dict[str, Any],
        response_queue_id: int,
        uid: str,
        lit_api: LitAPI,
        transport: MessageTransport,
        callback_runner: CallbackRunner,
    ) -> None:
        meta = payload["_stream_meta"]
        msg_type = meta["msg_type"]
        stream_id = meta["stream_id"]
        data = {k: v for k, v in payload.items() if k != "_stream_meta"}

        if msg_type == "STREAM_OPEN":
            with self._session_lock:
                if stream_id in self.sessions:
                    return
                session = StreamSession(
                    stream_id, lit_api, transport, response_queue_id, self
                )
                self.sessions[stream_id] = session
            session.start()
            if self._restart_workers:
                self.put_response(
                    transport, response_queue_id, stream_id, (),
                    LitAPIStatus.START, LoopResponseType.STREAMING,
                )

        elif msg_type == "STREAM_CHUNK":
            with self._session_lock:
                session = self.sessions.get(stream_id)
            if session:
                session.push_chunk(data)

        elif msg_type == "STREAM_CLOSE":
            with self._session_lock:
                session = self.sessions.pop(stream_id, None)
            if session:
                session.close()

        elif msg_type == "STREAM_CANCEL":
            with self._session_lock:
                session = self.sessions.pop(stream_id, None)
            if session:
                session.cancel()

    def _process_request(
        self,
        response_queue_id: int,
        uid: str,
        timestamp: float,
        payload: dict[str, Any],
        lit_api: LitAPI,
        transport: MessageTransport,
        callback_runner: CallbackRunner,
    ) -> None:
        if self._restart_workers:
            self.put_response(
                transport, response_queue_id, uid, (),
                LitAPIStatus.START, LoopResponseType.STREAMING,
            )

        if (lit_api.request_timeout and lit_api.request_timeout != -1) and (
            time.monotonic() - timestamp > lit_api.request_timeout
        ):
            from fastapi import HTTPException
            self.put_response(
                transport, response_queue_id, uid,
                HTTPException(504, "Request timed out"),
                LitAPIStatus.ERROR, LoopResponseType.STREAMING,
            )
            return

        try:
            context = {}
            callback_runner.trigger_event(EventTypes.BEFORE_DECODE_REQUEST.value, lit_api=lit_api)
            x = _inject_context(context, lit_api.decode_request, payload)
            callback_runner.trigger_event(EventTypes.AFTER_DECODE_REQUEST.value, lit_api=lit_api)

            callback_runner.trigger_event(EventTypes.BEFORE_PREDICT.value, lit_api=lit_api)
            y_gen = _inject_context(context, lit_api.predict, x)
            callback_runner.trigger_event(EventTypes.AFTER_PREDICT.value, lit_api=lit_api)

            callback_runner.trigger_event(EventTypes.BEFORE_ENCODE_RESPONSE.value, lit_api=lit_api)
            y_enc_gen = _inject_context(context, lit_api.encode_response, y_gen)

            for y_enc in y_enc_gen:
                y_enc = lit_api.format_encoded_response(y_enc)
                self.put_response(
                    transport, response_queue_id, uid, y_enc,
                    LitAPIStatus.OK, LoopResponseType.STREAMING,
                )

            self.put_response(
                transport, response_queue_id, uid, "",
                LitAPIStatus.FINISH_STREAMING, LoopResponseType.STREAMING,
            )

            callback_runner.trigger_event(EventTypes.AFTER_ENCODE_RESPONSE.value, lit_api=lit_api)

        except Exception as e:
            logger.exception(f"BidirectionalStreamingLoop request error uid={uid}: {e}")
            self.put_error_response(
                transport, response_queue_id, uid, e, LoopResponseType.STREAMING,
            )
