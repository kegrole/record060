# timelinemerge

纯 Python 标准库实现的多源事件时间合并器：事件乱序到达、各来源延迟不同，
合并时按事件发生时间排序，并基于每来源水位线决定迟到事件的接纳与丢弃。

## 事件时间与处理时间

- `event_time`：事件实际发生的时间，也是输出排序与迟到判定使用的时间。
- `processing_time`：合并器实际观察/处理该事件的时间，代表到达顺序。
- 两者完全独立：一条很“老”的事件可以在很晚才被处理，这正是乱序与迟到的来源。

## 水位线推进规则

1. 对每个来源维护“当前已见到的最大 `event_time`”。
2. 来源水位线 = 该来源最大事件时间 − 该来源配置的延迟 `delay(source)`。
3. 全局水位线 = 所有来源水位线的最小值；尚未出现任何事件的来源暂不参与取最小值。
4. 全局水位线只允许单调不降：新候选值低于当前值时保持当前值不变。

## 迟到窗口语义

设当前全局水位线为 `W`，允许迟到窗口为 `L`：

- `event_time >= W`：按时到达，正常输出，`late = false`。
- `event_time < W` 且 `event_time >= W - L`：迟到但仍在允许窗口内，输出且
  `late = true`，计入 `late_accepted`。
- `event_time < W - L`：迟到且超出窗口，直接丢弃，计入 `dropped_late`。
- 边界 `event_time == W` 不算迟到；边界 `event_time == W - L` 仍在窗口内、予以接纳。

被接纳的事件最终按键 `(event_time, source, id)` 排序输出，因此同 `event_time`
先按 `source` 字典序、再按 `id` 字典序排列。处理顺序按
`(processing_time, source, id, event_time)` 确定，保证打乱输入文件行顺序后，
输出逐条一致。

## 输入格式

JSONL，每行一个事件对象：

```json
{"event_time": "2026-01-01T00:00:00Z", "processing_time": "2026-01-01T00:01:40Z", "source": "alpha", "id": "evt-001"}
```

各来源延迟可写在文件中的配置行（位置任意）：

```json
{"config": {"source_delays": {"alpha": "2s", "beta": "4s", "gamma": "6s"}}}
```

也可以用 `--sources` 传入独立的 JSON 映射文件。时长支持 `ms`、`s`、`m`、`h`
等单位（如 `500ms`、`5s`、`2m`、`1h`），裸数字按秒解释。

## 报告字段

- `final_watermark`：处理完所有事件后的最终全局水位线（ISO 8601）。
- `emitted`：实际输出条数。
- `dropped_late`：超出允许窗口而被丢弃的迟到事件数。
- `late_accepted`：迟到但落在窗口内、仍被输出的事件数。

报告还包含 `input_events`、完整 `output`（每条带 `late` 与判定时水位线）、
`dropped` 明细以及 `watermark_history`，便于核对水位线推进过程。

## 运行方式

```bash
python -m timelinemerge.cli --events demo/events.jsonl --allowed-lateness 5s --out out/report.json
```

成功后 stdout 打印一行摘要，例如：

```text
events=15 emitted=13 late_accepted=3 dropped=2
```

运行测试：

```bash
python -m unittest test_timelinemerge -v
```
