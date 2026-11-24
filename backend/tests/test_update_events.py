import unittest
from unittest.mock import patch

from cpu_data.application import update


def cpu(name):
    return {
        "name": name,
        "passmark_score": 100,
        "detail_url": "https://example.test/" + name,
    }


class UpdateEventTests(unittest.TestCase):
    def _patch_common(self, items):
        patches = [
            patch.object(update, "init_db"),
            patch.object(update, "fetch_cpu_list", return_value=items),
            patch.object(update, "get_meta", side_effect=lambda key: "false" if key == "update_in_progress" else None),
            patch.object(update, "set_meta"),
            patch.object(update, "upsert_many"),
            patch.object(update, "count_cpus", return_value=len(items)),
            patch.object(update, "BATCH_SIZE", 1),
        ]
        return patches

    def test_full_update_emits_progress_batch_and_completion_events(self):
        items = [cpu("CPU A"), cpu("CPU B")]
        events = []
        with patch.object(update, "init_db"), \
             patch.object(update, "fetch_cpu_list", return_value=items), \
             patch.object(update, "get_meta", side_effect=lambda key: "false" if key == "update_in_progress" else None), \
             patch.object(update, "set_meta"), \
             patch.object(update, "upsert_many"), \
             patch.object(update, "count_cpus", return_value=2), \
             patch.object(update, "fetch_nanoreview", side_effect=[{"cores": "4"}, {}]), \
             patch.object(update, "_parse_specs", side_effect=lambda name, *_: update._record_without_specs(next(x for x in items if x["name"] == name))), \
             patch.object(update, "BATCH_SIZE", 1):
            result = update.run_update(event_handler=events.append, request_delay_seconds=0)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.processed, 2)
        self.assertIsInstance(events[0], update.UpdateStarted)
        progress = [event for event in events if isinstance(event, update.UpdateProgress)]
        self.assertEqual([event.status for event in progress], ["success", "not_found"])
        self.assertEqual(len([event for event in events if isinstance(event, update.UpdateBatchSaved)]), 2)
        self.assertIsInstance(events[-1], update.UpdateCompleted)

    def test_cancellation_flushes_records_and_keeps_checkpoint(self):
        items = [cpu("CPU A"), cpu("CPU B")]
        events = []
        token = update.CancellationToken()
        set_meta = unittest.mock.Mock()

        def cancel_after_wait(_delay):
            token.cancel()

        with patch.object(update, "init_db"), \
             patch.object(update, "fetch_cpu_list", return_value=items), \
             patch.object(update, "get_meta", side_effect=lambda key: "false" if key == "update_in_progress" else None), \
             patch.object(update, "set_meta", set_meta), \
             patch.object(update, "upsert_many") as upsert_many, \
             patch.object(update, "count_cpus", return_value=1), \
             patch.object(update, "fetch_nanoreview", return_value={"cores": "4"}), \
             patch.object(update, "_parse_specs", side_effect=lambda name, *_: update._record_without_specs(next(x for x in items if x["name"] == name))): 
            result = update.run_update(
                event_handler=events.append,
                cancellation_token=token,
                request_delay_seconds=1,
                wait=cancel_after_wait,
            )

        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.processed, 1)
        self.assertEqual(len(upsert_many.call_args.args[0]), 1)
        set_meta.assert_any_call("update_checkpoint", "CPU A")
        set_meta.assert_any_call("update_in_progress", "true")
        self.assertIsInstance(events[-1], update.UpdateCancelled)

    def test_failure_emits_failed_event_and_propagates(self):
        events = []
        items = [cpu("CPU A")]
        with patch.object(update, "init_db"), \
             patch.object(update, "fetch_cpu_list", return_value=items), \
             patch.object(update, "get_meta", side_effect=lambda key: "false" if key == "update_in_progress" else None), \
             patch.object(update, "set_meta"), \
             patch.object(update, "upsert_many"), \
             patch.object(update, "fetch_nanoreview", side_effect=RuntimeError("network unavailable")):
            with self.assertRaisesRegex(RuntimeError, "network unavailable"):
                update.run_update(event_handler=events.append, request_delay_seconds=0)

        self.assertIsInstance(events[-1], update.UpdateFailed)
        self.assertEqual(events[-1].processed, 0)

    def test_fast_update_emits_completion_event(self):
        events = []
        items = [cpu("CPU A")]
        with patch.object(update, "init_db"), \
             patch.object(update, "fetch_cpu_list", return_value=items), \
             patch.object(update, "set_meta"), \
             patch.object(update, "upsert_many"), \
             patch.object(update, "count_cpus", return_value=1):
            result = update.run_update(fast=True, event_handler=events.append)

        self.assertEqual(result.status, "completed")
        self.assertIsInstance(events[-1], update.UpdateCompleted)


    def test_resumed_full_update_progress_count_is_run_relative(self):
        items = [cpu("CPU A"), cpu("CPU B"), cpu("CPU C"), cpu("CPU D")]
        events = []
        meta = {
            "update_in_progress": "true",
            "update_checkpoint": "CPU B",
            "update_cpu_list_fingerprint": update._cpu_list_fingerprint(items),
        }
        with patch.object(update, "init_db"), \
             patch.object(update, "fetch_cpu_list", return_value=items), \
             patch.object(update, "get_meta", side_effect=lambda key: meta.get(key)), \
             patch.object(update, "set_meta"), \
             patch.object(update, "upsert_many"), \
             patch.object(update, "count_cpus", return_value=4), \
             patch.object(update, "fetch_nanoreview", return_value={"cores": "4"}), \
             patch.object(update, "BATCH_SIZE", 1):
            result = update.run_update(
                event_handler=events.append,
                request_delay_seconds=0,
            )

        progress = [
            event for event in events
            if isinstance(event, update.UpdateProgress)
        ]
        self.assertEqual(result.processed, 2)
        self.assertEqual([event.processed for event in progress], [1, 2])
        self.assertEqual([event.position for event in progress], [3, 4])
        self.assertEqual([event.total for event in progress], [4, 4])


if __name__ == "__main__":
    unittest.main()
