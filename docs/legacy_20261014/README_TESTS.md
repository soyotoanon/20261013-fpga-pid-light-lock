# adc_pi_loop 上机测试与标定步骤

配合 `README.md`（工程概览）与 `README_REGISTERS.md`（**寄存器与串口协议权威手册**）使用。
本文只讲"怎么一步步在硬件上验证"，寄存器地址一律不在本文重复，需要时查寄存器手册，
或者直接用 `host\llctl.py` 的命名开关。

> **顺序不要跳。** 每级都建立了才进下一级，否则后面出问题无法归因。
> 尤其**不要一上来就跑闭环**。

---

## 0. 上电前（断电检查）

- [ ] **J2 / J3 的 54 脚贴胶带**。这两脚是 +3.3 V，接了会打坏模块。
- [ ] 供电**全部取自开发板**：ADC 从 J3-56/55、DAC 从 J2-56/53/55。
- [ ] 50 根数字线按 `..\WIRING.md` 接到 J2，逐脚核对（脚位表也在 `README.md` §2）。
- [ ] **DAC 的 CH1 / CH2 先各接 1 MΩ 高阻到示波器**，暂时**不接** AOM、不接 DDS。
- [ ] 确认你的 AD9248 模块是 3.3 V 还是 1.8 V IO 版本，CLK 方向对不对。
      ⚠️ 这一条至今**没核实过**，接错会烧 IO。
- [ ] 确认 AD9767 模块上两个蓝色电位器已拧满（影响 I-V 级满量程）。

---

## 1. 上电、烧写、串口连通（【05】）

1. 烧 `bitstream\light_lock_top.bit`。
2. 看 `led_heartbeat`（R2）在闪 ⇒ 时钟与复位正常。
3. 板载 Type-C 插电脑，确认串口出现（`uart_rx=U5` / `uart_tx=T6`，**不需要飞线**）。
4. 读状态：

```bash
python host/llctl.py --port COM5 --info
python host/llctl.py --port COM5 --read 0x01     # STATUS
```

- STATUS 各位含义见 `README_REGISTERS.md`。上电后应当是"光丢失"置位（没光）、
  其余为 0；**ADC 时钟停摆位必须为 0**。
- 若 `--info` 完全无响应：`BAUD_DIV` 默认 434 = 50 MHz / 115200，确认波特率是
  115200 8N1；再确认 `sys_clk` 真的是 50 MHz。

---

## 2. ADC 采样与时钟（【01】）

1. 示波器量 **J2-15（`adc_clk`）**：应为 **5 MHz、约 50% 占空**。
   不是 5 MHz 就查 `ADC_HALF`（默认 4；**要 5 MHz 必须写 4，不是 5**，
   因为 `adc_drv.v` 里 `div_cnt` 复位为 0，实际周期是 `2×(half+1)` 拍）。
2. 量 **J2-16（`adc_oeb_n`）应为低**、**J2-18（`adc_pdn`）应为低**。
3. 给 PA 一个已知直流电压，读码看是否跟着动：

```bash
python host/llctl.py --port COM5 --read 0x02      # live ADC 码
```

- 偏移二进制：`0x2000` = 中点（0 V 差动）。
- 顺便**反推满量程**——这就是 `tools\pd_convert.py --span` 需要的那个数，
  没有它后面所有功率换算都是假的。
- 给超出量程的输入，看 STATUS 的 **OTR** 位是否锁存；然后 `--clear-flags` 清掉。

---

## 3. DAC 输出与波形（【02】【04】）

### 3.1 先静态验证码 ↔ 电压

用固定码模式（`SIG_MODE = 0`），万用表量 CH1：

| 码 | 期望（模块 I-V 级已校准时） |
| --- | --- |
| `0x0000` | −5 V |
| `0x2000` | 0 V |
| `0x3FFF` | +5 V |

- 量出来的直线不直、或端点不到 ±5 V ⇒ 拧模块电位器、或查 I-V 级。
- AD9767 **是电流输出 20 mA**，±5 V 是模块上 I-V 级做的，**FPGA 里没有任何换算**。
- 14 位 / ±5 V ⇒ **0.61 mV/步**，这是本工程精度的硬上限。

### 3.2 再验波形

```bash
python host/llctl.py --port COM5 --sine --amp 1024 --period 64 --offset 0x2000
python host/llctl.py --port COM5 --stop-sig
```

- `SIG_MODE`：0 固定码 / 1 方波 / 2 阶跃 / 3 锯齿 / 4 三角 / 5 正弦。
- 示波器应看到以 `0x2000` 为中心、幅度约 ±1024 码（≈±0.62 V）的正弦。
- ⚠️ **`SIG_EN[1]`（update）是电平不是脉冲**。写完必须把它清掉只留 enable，
  否则模块每拍把相位清零，波形"输出不动"（这是早期踩过的真根因）。
  `llctl.py` 已经帮你处理了；如果你手写寄存器，务必自己清。
- 波形频率 = 控制节拍 / `SIG_PERIOD`。默认 50 kHz / 1000 = 50 Hz。

---

## 4. 直通验证（【03】）

`CTRL[1]` 置位进直通：ADC 码直送 DAC。给 PA 一个斜坡或交流信号，
示波器在 DAC 输出应看到**跟着动、相位延迟约 1~2 µs**（AD9248 流水线延迟，
正常现象）。通道接反了用顶层参数 `SWAP_CHANNELS` 调，**不要去重接线**。

---

## 5. ⚠️ 数字链路延迟测试（【06】）—— **当前跑不了**

`dbg_marker.v` 与 ILA 实例都在 `light_lock_top.v:460-484` 的
（**第四轮审查再核**：原写 `:412-434`、后又写 `:458-479`、`:461-479`，现按文件实际行号复核 —— `` `ifdef `` 在 462、`dbg_marker` 实例 464-471、`ila_light_lock` 实例 473-483、`` `endif `` 在 484。）
`` `ifdef ILA_ENABLE `` 内（默认构建**刻意不含**调试核，这是对的，别把 ILA 带进正式 bit）。
但有两个缺口，**要真跑这条测试必须先补**：

1. 工程里**没有 `ila_light_lock` 这个 IP**。一旦定义 `ILA_ENABLE`，综合会因
   unresolved module 失败。要做就得在 Vivado 里生成这个 ILA 核并加进构建。
2. `marker_adc` / `marker_dac` **只接到了 ILA，没有引到任何封装引脚**。
   `dbg_marker.v` 注释里写的"各引一根线到示波器"目前**做不到**。
   要么把这两个信号加成顶层输出端口并补 XDC，要么改用 ILA 观察。

原理（等补好之后可用）：`marker_adc` 在 ADC 时钟上升沿置位、`marker_dac` 在
DAC 更新时置位，两沿之间的时间差就是"ADC 采样沿 → DAC 数据更新"的数字延迟。
比在 ILA 里数采样点准，因为**引脚传播延迟也被算进去了**。

---

## 6. AOM 标定扫描（【07】【08】【09】【10】）

```bash
# 【07】DAC 全量程扫描，每步保持一会儿
python host/llctl.py --port COM5 --sweep --start 0x0000 --end 0x3FFF --step-size 1
# 或者连续扫
python host/llctl.py --port COM5 --sweep --start 0x0000 --end 0x3FFF --step-size 1 --continuous
```

- 关键字：`SWEEP_START` / `SWEEP_END` / `SWEEP_STEP`（24 位）/ `SWEEP_HOLD` /
  `SWEEP_CTL`。**`SWEEP_CTL[2]`（启动）是电平不是脉冲**，写完要放掉。
- 同步记录 PD 读数：

```bash
# 【08】【18】按控制周期上传，落到 CSV
python host/llctl.py --port COM5 --log --every 64 --count 1000 --out sweep.csv
```

- 【09】统计量（均值/方差/最小/最大）在 FPGA 里算，窗口 = `2^STATS_LOG2`（端口 5 位，
  可写 0..31；**实用上取 0..16 就够**，写 >31 被静默截成低 5 位。`acc_sum` 46 位、
  `acc_sq` 92 位，`2^31` 个样本也不溢出——真正的限制是时间：`2^31` 个控制周期 ≈ 12 小时）。
  `mean = 累加和 >> STATS_LOG2`、`var_q4 = (E[x²] − E[x]²) × 16`，超 16 位饱和到 `0xFFFF`。
  读 `live_mean/var/min/max` 那几个只读寄存器。`--clear-stats`（`CTRL[10]`）**清累加器与极值**
  ——第二轮自查前它是死位；**min/max 是自 clr/上电以来的极值**，不是"窗口内"。
  统计口径的回归见 `tb/tb_adc_stats.v`（16 项）。
- 【10】换算**在上位机**做：

```bash
python tools/pd_convert.py --code 12345 --span 2.0 --slope <你自己拟合的斜率>
```

> ⚠️ **旧标定式 `P_main[mW] = 6.778411×V_PD + 0.5777915` 已作废**：
> 它是按 PD 负载 **1 MΩ** 标的，而现在 PD 用 **50 Ω 档直进 AD9248 PA**，
> 负载差两个数量级，那条直线不再成立。`pd_convert.py` 因此**不内置任何系数**，
> 必须你自己用功率计标定后把 `--slope/--intercept`（或 `--responsivity`）传进来。
> 在标定之前，`pd_convert.py` 只输出电压。

由扫描曲线定出 AOM 工作点：留 **20~30% 余量**，别顶到端点。

---

## 7. DDS 工作点（【11】）

- 控制电压进 **DDS 的 ADC 口**，RF 从 **CH8 恒 100 MHz** 出。
- DDS 走**网口**不是串口（Qosmos SDK 默认 `192.168.1.104:8082`）。
- ⚠️ **DDS 振幅控制字 13 位 vs 本工程 DAC 14 位，必然丢一位**。
  丢 LSB（精度 0.61→1.22 mV）还是丢 MSB（浪费一半量程）**必须实测再定**，
  切换点是 `hw_params.vh` 的 `DDS_CTRL_DROP_LSB`（默认丢 LSB）。
- ⚠️ DDS VCO 输入口的**输入阻抗 / 是否 DC 耦合 / 允许输入电压**至今**没查到**
  （等厂家答复）。若只吃 0~1 V，DAC 的 ±5 V **必须先衰减**，否则可能打坏输入口。

---

## 8. PI 闭环（【12】【13】【14】【15】【16】）

**先小增益，再逐步加。** 误差在 ADC 码域算，`u[n] = u0 + Kp·e[n] + I[n]`，
`I[n+1] = I[n] + Ki·Ts·e[n]`（`Ki·Ts` 在 FPGA 内合并成一个离散积分增益）。

```bash
python host/llctl.py --port COM5 --setpoint 8192           # 【12】目标码
python host/llctl.py --port COM5 --pi 8 14 --enable        # 【16】Kp/Ki 然后【14】进闭环
python host/llctl.py --port COM5 --disable                 # 退闭环
```

- `KP_SHIFT` / `KI_SHIFT` 是**移位量**，Kp = 1/2^shift，所以**数值越大增益越小**。
  从 `KP_SHIFT` 大（增益小）开始试。
- `--pi a b` 两个参数是 `(KP_SHIFT, KI_SHIFT)`。
- 输出限幅 `OUT_MIN/OUT_MAX`、积分限幅 `I_CLAMP` 先设保守一点。
- 方向反了改 `DIR_POL`，别去改接线。

### 保护（【15】）

- **光丢失 ⇒ 整环冻结**：PD 读数低于 `LIGHT_TH` 连续若干拍 ⇒ `light_lost` 置位、
  `frozen` 置位，输出保持在冻结前那一刻的值。
- **OTR**（ADC 过载）与**输出/积分饱和**也各自锁存一个 sticky 位。
- 解冻/复位用清标志：`--clear-flags`。
  ⚠️ **`CTRL[9]`（清标志）是电平不是脉冲**——一旦置位，光丢失计数器每拍被清零、
  永远到不了阈值。所以清完必须**把该位放掉**（`llctl.py --clear-flags` 已处理）。
- 掉光实验：挡住光，看 STATUS 的光丢失位与冻结位。
- `led_status[1:0]`（V2/R3）默认 = `STATUS[1:0] = {OTR, 光丢失}`，可用 `CTRL[12:11]`
  改选 `STATUS[3:2]` / `STATUS[5:4]` / `STATUS[7:6]`（`llctl.py: set_led_src()`）。
  （**第四轮审查更正**：本文件曾写"`led_status[0]` = ADC 采样的一位"，那是更早的实现。）

---

## 9. 闭环性能与带宽（【17】【18】【19】）

```bash
python host/llctl.py --port COM5 --step --dist-amp 64 --dist-period 4096   # 【17】阶跃扰动
python host/llctl.py --port COM5 --dist-sine --dist-amp 64 --dist-period 4096  # 【19】正弦扰动
python host/llctl.py --port COM5 --dist-off
python host/llctl.py --port COM5 --log --every 64 --count 1000 --out step_resp.csv  # 【18】
```

- 扰动灌在**设定值**上（`sp_sum` 把 `dist_delta` 加到设定值再夹取），不是直接加在输出上。
- `DIST_MODE`：0 关 / 1 阶跃 / 2 方波 / 3 正弦 / 4 三角。
- **`DIST_EN[1]`（update）同样也是电平不是脉冲**，道理和 `SIG_EN[1]` 一样。
- 【18】的记录按 `LOG_EVERY` 个控制周期上传一次，由 `log_arbiter.v` 仲裁，
  和寄存器读回复用同一条串口。
- 扫频率就能画 Bode 图，看闭环带宽与相位裕度。

> **周期口径（2026-10-14 自查统一，已修）**：一圈 = `DIST_PERIOD` 个控制周期，
> 阶跃/方波/正弦/三角四种波形一致。控制周期默认 `2×(CTRL_HALF+1) = 1000` 个
> `sys_clk` = 20 µs ⇒ `DIST_PERIOD=4096` 时一圈约 **82 ms**（≈12 Hz），
> `DIST_PERIOD=64` 时约 1.28 ms。
> 改前正弦/三角实际是 `256 × DIST_PERIOD²`（对 `DIST_PERIOD` 平方），
> `DIST_PERIOD=4096` 时一圈要 **16 天** —— 扫频必须按**改后**的口径算。
> 详见 `README_REGISTERS.md` §4.6，回归见 `tb/tb_step_gen.v`（扰动 18 项）。
> 【07】自动扫描的回归见 `tb/tb_sweep_gen.v`（**26 项**）：覆盖跨中点 `0x2000` 的上下扫描、
> 每步保持拍数、负 `step_code` 取幅值、`start == end`、连续模式来回扫与端点码。
> 【09】【10】统计口径的回归见 `tb/tb_adc_stats.v`（**16 项**）：窗口正好 `2^log2_n` 个样本、
> 均值按 `log2_n` 移位（不是参数 `LOG2_W`）、`var_q4` 公式、`clr` 清零极值、方差饱和。
> 【05】串口链路的回归见 `tb/tb_uart_loop.v`（**28 项**，2026-10-14 第三轮自查新增）：
> 它把 `uart_proto + log_arbiter + uart_tx` 串起来，在 `tx_pin` 上**自己解码 UART**、
> 按线上顺序逐字节断言 —— 读应答必须正好 8 字节 `C5 cmd addr dataL dataH 5C C5 C5`、
> **不许重发**、写帧不许有应答、数据流帧、读应答优先于数据流、帧尾 `0xC5` 校验失败
> **绝不写寄存器**。此前全 tb 目录从不解析回帧，所以"每字节被发两次""读应答无限重发"
> "帧尾不校验"这三个缺陷一个都没被发现。
>
> **2026-10-14 第四轮自查新增的两份"真闭环"回归（此前 10 份 tb 里一次都没闭过环）**：
> - `tb/tb_pi_loop.v`（**35 项**）：只测 `pi_ctrl`，被控对象是一阶惯性模型（**1/8 码分辨率**，
>   避免模型自己的整数截断被误判成控制器静差）。覆盖：默认 `I_CLAMP` 下的积分撞钳平台、
>   放大 `I_CLAMP` 后真收敛（静差 ≤7 码 = 积分量化死区 `2^(KI_SHIFT-9)`）、`DIR_POL=0`
>   推下轨、不可达目标的输出轨饱和与积分精确夹住、`freeze`、`CTRL[4] set_valid`、
>   `clr_i`、`enable=0` 保持、纯积分收敛、`KI_SHIFT>22` 被钳到 22（积分步长仍为 1）。
> - `tb/tb_light_loop.v`（**178 项**）：整片 `light_lock_top`，串口**只走 uart_rx/uart_tx
>   引脚、用真 8 字节帧**收发，`da1_data` 经一阶惯性回到 `adc_d` ⇒ **真的闭环**。
>   覆盖：上电默认值真帧读回、写→读回、相邻地址不串扰、只读地址写无效、保留区读 0、
>   闭环收敛（`0x23F9` vs 目标 `0x2400`）、`DIR_POL=0` 推下轨、默认 `I_CLAMP` 的平台
>   `0x303E`（理论 `0x303F`）、放大后贴满量程、`sp_final` 三段饱和、控制节拍 = 1000 clk、
>   `CTRL[12:11]` 选 LED 字节、DA2 与 DA1 同码。
>   ⇒ 靠它才抓出并修掉 `pi_ctrl.v` 抗饱和的真缺陷（见 `README_REGISTERS.md` §3.5）。
> - `tb/tb_sig_audit.v`（**41 项**，第四轮从"0 断言"改成真判定）：四种波形的幅度口径
>   （方波/三角精确 ±、锯齿 `offset..offset+amp-1`、正弦 `±(32767·amp_norm2)>>15`）、
>   不越 14 位、以及**摆幅随 `SIG_AMP` 单调增**（旧 bug 是相反：正弦 amp≥0x2000 被当负数）。

---

## 10. 还没有实现的两项

| 项 | 状态 |
| --- | --- |
| 【20】输出平滑与滤波 | **RTL 里没有实现**（没有任何平滑/滤波模块）。目前只有 PI 输出直接送 DAC。 |
| 【21】双通道反馈控制 | **没有实现第二路闭环**。`light_lock_top.v:178` 是 `assign dac2_code = bias_r[13:0];` —— 而且这条赋值是**死码**（下游 `adc_dac_core.v:64-65` 的 `.data1/.data2` 都接 `code_to_dac`）⇒ **DA2 实际输出与 DA1 同一个码**。要真做双通道必须改 `adc_dac_core` 的两路数据源。 |

要做得另外加模块，现状先按单通道用。
