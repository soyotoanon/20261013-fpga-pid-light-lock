# 原始数据说明

这个仓库的主体是 Verilog 源码和构建脚本。`data/` 下面放的是**少量关键测量数据**——只放那些"没有它就没法复核仓库结论"的，不做数据全集归档。

下面每一项都写清楚：什么数据、什么时候测的、多少点、什么条件、以及**它能证明什么、不能证明什么**。

## data/20261020-power-sweep-10289/

主光路功率扫描，10289 点。**这是本仓库功率显示标定的原始输入数据。**

| 文件 | 大小 | 内容 |
|---|---|---|
| `points.csv` | 1,177,192 B | 1 行表头 + 10289 行数据 |
| `metadata.json` | 911 B | 采集时记录的会话元数据 |

采集信息（来自 `metadata.json`，原样记录）：

- 会话 ID：`20261020_153506_595958_REAL`，`created_utc` = `2026-10-20T07:35:06.596961+00:00`，即北京时间 **2026-10-20 15:35**，连续采集。
- 条件：**556 nm MOT 单束**。
- 功率计：Thorlabs **PM100USB，SN `P2007293`**，波长档 556 nm，单位 W，VISA `USB0::0x1313::0x8072::P2007293::INSTR`。
- ADC：5 MS/s，每帧窗口 262144 样本（偏移二进制码；固件对双补码先 XOR bit13 再平均）。
- 串口 COM9，115200 波特。
- 时间对齐：`nearest host timestamp, max skew 0.2 s, not hardware sync` —— 功率计读数和 ADC 采样是**按主机时间戳就近配对**的，不是硬件同步触发。每行的 `pair_skew_ms` 就是这一次配对的实际偏差（毫秒）。

`points.csv` 字段：

| 列 | 含义 |
|---|---|
| `time_s` | 从采集开始算的秒数 |
| `power_mw` | 功率计读数，mW |
| `code` | 同一时刻的 ADC 平均数字码（14 bit，偏移二进制） |
| `power_std_mw` | 配对窗口内功率计读数的标准差，mW |
| `code_std` | ADC 码的标准差 |
| `reference_n` | 参与平均的功率计读数个数 |
| `adc_frames` | 参与平均的 ADC 帧数 |
| `mode` | 该点采集模式标记 |
| `pair_skew_ms` | 功率计读数与 ADC 采样时间戳的偏差，ms |

> 行尾是 `<CR><CR><LF>`，这是采集程序当时的原始写盘格式，没有做二次清洗——保留原样是为了让任何人能用 sha256 校验这份数据就是标定的输入。

**它能证明什么**：`calibration/calibration_20261020.json` 和 `calibration/piecewise_20261020.json`（`piecewise_intervals = 30`，code/power 节点各 31 个，`n = 10289`）都是从这份数据拟合出来的，可以用它从头复算这两个文件、复现 `calibration/fit30.png`。
**它不能证明什么**：这份数据本身不包含闭环验证信息，闭环性能看 `validation/`。

## 仓库里原有的其它数据文件

这些在更早的提交里，一起说明来历：

| 文件 | 大小 | 内容 |
|---|---|---|
| `calibration/calibration_20261020.json` | 259,279 B | 全局标定结果，含残差数组（长度 10289，与上面的 `points.csv` 行数一致） |
| `calibration/piecewise_20261020.json` | 4,990 B | 30 段分段标定，31 个 code/power 节点 |
| `calibration/fit30.png` / `.pdf` | 339,902 / 597,123 B | 30 段拟合曲线图 |
| `calibration/equations30.png` / `.pdf` | 739,228 / 40,557 B | 30 段各段方程与系数 |
| `validation/scan_samples.csv` | 39,095 B | 60 秒扫掠的 251 个采样点 |
| `validation/hardware_new.json` | 116,447 B | 上板读数 vs 功率计，n = 251，RMSE 0.1719 mW |
| `validation/scan60.png` / `.pdf` | 211,822 / 50,487 B | 60 秒扫掠曲线 |
| `validation/scan_summary.json` | 2,079 B | 扫掠汇总 |
| `validation/low_power_detail.json` | 641 B | 低功率段细节 |
| `validation/20261020/results.json` | 441 B | 2026-10-20 验证结论 |
| `validation/simulation_results.json` | 433 B | RTL 仿真结果 |
| `SHA256.json` | 10,806 B | 已发布文件的哈希清单 |

## 没有放进仓库的数据

以下数据在本机存在，但**没有上传**，原因逐条说明：

- **2026-10-16 上板调试数据**：`pd_adc_dac_live_20261016.csv`（100 行，PD 电压 / ADC 码 / 误差 / DAC 码 / RF 幅度）、`integral_board_test_20261016.csv`（60 行积分项验收）、两份 DDS 调幅斜率 probe JSON。这些是**单次诊断记录**，没有记录当时的环境光状态，条件不完整，不适合作为可引用的数据集；它们的结论已经以文字和数字形式写在 `VALIDATION.md` 里。
- **2026-10-20 的 80 段中间版上板数据**：那一版的读数来自界面显示、未与硬件同步、PI 关闭，且该版本已被 30 段版取代，数据不进入本仓库。
- **示波器截图和 `direct_captures/` 原始采集目录**：截图是看图性质的中间产物，采集目录体积大且已在整理过程中清理。
- **上位机 DEMO 模式的界面演示录制**：是演示用的模拟数据，不是测量数据。