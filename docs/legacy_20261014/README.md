# adc_pi_loop —— AOM 光强锁定闭环控制器

达芬奇 ATK-DF7A35 上的单环光强锁定控制器：把光电二极管（PD）的读数经 AD9248
采进 FPGA，与目标光强比较后做 PI 运算，再从 ACM9767 输出控制电压去驱动 AOM
（或直接驱动 DDS 的 VCO 控制口），使 PD 读数锁在设定值上。

本目录是**独立于 `passthrough_5mhz_ob\` 的第二个固件工程**。`passthrough_5mhz_ob\`
只做"低速直通"用于首次上机验证链路，本工程才是带串口、带 PI、带标定工具的完整版。

---

## 1. 信号链

```
PD ──► AD9248 (14bit, 5MHz) ──► FPGA ──► ACM9767 (AD9767, 14bit, ±5V) ──► AOM / DDS VCO
                                  │
                                  └──► UART (板载 Type-C) ──► PC (host/llctl.py)
```

- **ADC**：AD9248 模块，偏移二进制 14 位，`0x2000` = 中点 = 0 V。
  采样时钟由 FPGA 产生（不是外部晶振），默认 5 MHz。
- **DAC**：ACM9767（AD9767）。**芯片本身是电流输出型，满量程 20 mA**，
  双极性 ±5 V 由模块上的 I-V 级运放完成，**不在 FPGA 内**（依据
  `_scratch\alientek\AN9767REV1.0.pdf.txt` 第 160/164/186-194 行）。
  14 位 ⇒ ±5 V 量程下 **0.61 mV/步**。同样用偏移二进制，`0x2000` = 中点。
- **供电**：全部取自开发板。ADC 由 J3-56/55 供电，DAC 由 J2-56/53/55 供电。
  ⚠️ **J2/J3 的 54 脚是 +3.3 V，绝不能接**（接线时贴胶带）。
- **50 根数字线全部走 J2 飞线**，脚位见下表与 `..\WIRING.md`。

---

## 2. 引脚（已逐脚写死在 `constraints\davinci_adc_pi_loop.xdc`）

| 功能 | 引脚 | 板/排针位置 |
| --- | --- | --- |
| `sys_clk` 50 MHz | R4 | 板载晶振 |
| `sys_rst_n` | U2 | 板载复位 |
| `adc_d[13:0]` | R17 J16 N15 P19 M17 P20 M16 M15 L15 L14 J17 K17 K18 K19 | J2-1..14 |
| `adc_clk` | H19 | J2-15 |
| `adc_oeb_n` | J19 | J2-16 |
| `adc_otr` | F20 | J2-17 |
| `adc_pdn` | F19 | J2-18 |
| `da1_data[13:0]` | K16 L16 L20 L19 T20 U20 N19 N18 M20 N20 J21 J20 G20 H20 | J2-19..32 |
| `da1_clk` | L18 | J2-33 |
| `da1_wrt` | M18 | J2-34 |
| `da2_data[13:0]` | F21 F18 E17 D17 N22 M22 M21 L21 K22 K21 J22 H22 G22 G21 | J2-35..48 |
| `da2_clk` | E19 | J2-49 |
| `da2_wrt` | D19 | J2-50 |
| `uart_rx` | U5 | 板载 Type-C（**不用飞线**） |
| `uart_tx` | T6 | 板载 Type-C |
| `led_heartbeat` | R2 | 板载 LED |
| `led_status[0]` | R3 | 板载 LED |
| `led_status[1]` | V2 | 板载 LED |

串口走**板载 Type-C**，脚位取自 `DaVinci_FPGA_IO.xdc` 的 `#---UART---` 段。
ADC 数据与 OTR 在 XDC 里声明为 `set_false_path`（本设计有意把外部数据当异步处理，
见 XDC 第 67-70 行的说明）。

---

## 3. 目录结构

```
adc_pi_loop\
  rtl\            19 个 .v + hw_params.vh（`include 引入，必须 -i 指定 rtl 目录）
  tb\             10 个 testbench（含自查新增的 6 个）
  constraints\    davinci_adc_pi_loop.xdc    引脚与时序约束
  scripts\        build.tcl / build.cmd      Vivado 批处理构建
  host\           llctl.py                   上位机（pyserial）
  build\          综合/实现报告与 checkpoint（构建产物）
  bitstream\      light_lock_top.bit
  README.md              本文件
  README_REGISTERS.md    ★ 寄存器与串口协议权威手册
  README_TESTS.md        上机测试与标定步骤
```

### RTL 模块

| 文件 | 作用 |
| --- | --- |
| `light_lock_top.v` | 顶层，串起全部子模块 |
| `adc_dac_core.v` | 引脚级 ADC/DAC 核心（例化 adc_drv/dac_drv） |
| `adc_drv.v` | ADC 采样时钟发生与数据采集 |
| `dac_drv.v` | DAC 双通道输出时序驱动 |
| `dac_sig_gen.v` | DAC 波形发生器（固定码/方波/阶跃/锯齿/三角/正弦） |
| `step_gen.v` | 扰动发生器，把扰动灌到设定值上（阶跃/方波/正弦/三角） |
| `sweep_gen.v` | DAC 码自动扫描（起止码 + 步长 + 保持时间） |
| `pi_ctrl.v` | PI 控制器（误差在 ADC 码域算） |
| `monitor.v` | 光丢失 / OTR / 输出饱和监视，触发整环冻结 |
| `adc_stats.v` | ADC 统计（均值/方差/最小/最大，2^N 窗口） |
| `ctrl_tick.v` | 控制周期节拍发生器 |
| `reg_file.v` | 64×16 寄存器堆（上电默认值由 `default_value` 函数给出，可综合） |
| `uart_rx.v` / `uart_tx.v` | 串口物理层 |
| `uart_proto.v` | 串口帧协议（**定长 8 字节**：`C5 01 <addr> <dataL> <dataH> 5C C5 C5`） |
| `log_arbiter.v` | 串口日志上传仲裁（扰动响应记录用） |
| `add_sat.v` | 饱和加法 |
| `recip_pow2.v` | 多周期精确除法器 `2^K / d`（避免组合除法成为时序瓶颈） |
| `dbg_marker.v` | 【06】数字链路延迟测试标记（**仅在 ILA_ENABLE 下综合**，见 §7） |

---

## 4. 构建

需要 **Vivado 2023.2**（本机在 `D:\xilinx\Vivado\2023.2`）。

```bat
cd adc_pi_loop
vivado.bat -mode batch -notrace -source scripts\build.tcl
:: 或直接双击 scripts\build.cmd
```

`build.tcl` 会跑 synth → opt → place → phys_opt → route → DRC → 时序报告 → bitstream，
最后**检查 WNS，为负则 `error` 让构建失败**，成功打印 `BUILD_PASS`。

- 器件：`xc7a35tfgg484-2`
- 产物：`bitstream\light_lock_top.bit`，报告在 `build\`
- **新增 RTL 文件必须手动加进 `build.tcl` 的 `rtl_files` 列表**（它用显式文件名列表
  `read_verilog`，不会自动扫描 `rtl\`），否则综合报 unresolved module。

### 当前构建结果（已验证）

| 项 | 值 |
| --- | --- |
| WNS (setup) | **+4.536 ns**（2828 端点，0 条失败） |
| WHS (hold) | +0.052 ns（2828 端点，0 条失败） |
| WPWS | +9.500 ns（1533 端点，0 条失败） |
| 综合/实现错误 | 0 Errors, 0 Critical Warnings（`Synthesis finished with 0 errors, 0 critical warnings and 19 warnings.`） |
| DRC | 0 Errors；`build\drc.rpt` 共 28 条 Warning：`DPIP-1` 14 / `DPOP-1` 7 / `DPOP-2` 7，全是 DSP 输入/输出流水建议，无害 |

时序收敛过程：初始 **−19.330 ns** →（把 `dac_sig_gen`/`step_gen` 的组合除法换成
`recip_pow2` 顺序除法）**−2.554 ns** →（把 `step_gen` 的 `tri2sin` 多项式切成
5 级流水）**+4.182 ns** →（第一轮自查修 11 处缺陷后重出片）**+4.862 ns** →
（第二轮重写 `adc_stats` 时写成 46×46 位乘法，它成了全设计最差路径
`u_stats/acc_sum_reg[0] → u_stats/var_q4_reg[7]`）**+0.731 ns** →
（把两个乘法按真实数据位宽收窄成 14×14 与 15×15，见 `rtl\adc_stats.v` 文件头 ④）**+3.999 ns** →
（第三轮自查重写 `uart_proto` 帧 FSM 与 `log_arbiter` 握手后重出片）**+4.536 ns**。

> 上表是 **2026-10-14 第三轮自查修复后**的实测值，取自 `build\timing_summary.rpt`
> （L194：`4.536 0.000 0 2828 … 0.052 0.000 0 2828 … 9.500 0.000 0 1533`，
> L197 `All user specified timing constraints are met.`），
> 构建日志 `build\vivado_console_round4.log` 末尾为 `FINAL_WNS=4.536` + `BUILD_PASS`；
> 当前比特流为 **832,472 B**，SHA-256 `1D9D6FEBB92F7A1B2DA25A28E7AA11C138622F26A2723DEE7E38EAEFB01A6DD3`。

> ⚠️ `xvlog` 容忍隐式 wire 与越界位选（只告警或不报），**只有综合/实现才暴露**。
> 写完 RTL 至少要跑一次 `synth_design`，不能只靠 xsim。

---

## 5. 仿真与回归

```powershell
$env:PATH = "D:\xilinx\Vivado\2023.2\bin;" + $env:PATH
$proj = "D:\DSproject\workbench\tasks\ad9248_ad9767_passthrough\adc_pi_loop"
$rtl  = (Get-ChildItem "$proj\rtl\*.v").FullName
# 每个 tb 用独立目录，避免 xelab 复用陈旧 snapshot
& xvlog.bat --nolog -i "$proj\rtl" @($rtl + "$proj\tb\tb_light_lock.v")
& xelab.bat --nolog -debug typical tb_light_lock -s s1
& xsim.bat  s1 --nolog -runall | Out-File -Encoding utf8 out.txt
```

| testbench | 覆盖 | 结果 |
| --- | --- | --- |
| `tb_light_lock.v` | 全系统：串口读写、ADC/DAC、PI、监视、冻结、波形、扫描 | **22 通过 / 0 失败** |
| `tb_reg_probe.v` | 寄存器通路与波形发生器（层次化直写绕过串口） | **19 通过 / 0 失败** |
| `tb_sig_gen.v` | `dac_sig_gen` 单模块（峰值阈值已收紧到 `0x3F00`，能抓住压扁的正弦） | **7 通过 / 0 失败** |
| `tb_sig_lut.v` | 正弦查表与象限折返（Q15 定点）＋锯齿爬升口径 | **9 通过 / 0 失败** |
| `tb_pi_audit.v` | `pi_ctrl` 定点尺度、积分器、装订、冻结（自查后新增的常驻回归） | **25 通过 / 0 失败** |
| `tb_step_gen.v` | `step_gen` 扰动波形：周期口径、峰值、正负对称、方波/阶跃形状、amp 夹取（第二轮自查新增） | **18 通过 / 0 失败** |
| `tb_sweep_gen.v` | `sweep_gen` 自动扫描：跨中点上下扫描、每步保持拍数、负 `step_code` 取幅值、`start==end`、连续模式来回扫与端点码（第二轮自查新增） | **26 通过 / 0 失败** |
| `tb_adc_stats.v` | `adc_stats` 统计口径：窗口正好 `2^log2_n` 个样本、均值按 `log2_n` 移位、`var_q4` 公式、`clr` 清零极值、方差饱和（第二轮自查新增） | **16 通过 / 0 失败** |
| `tb_uart_loop.v` | 串口**端到端**：`uart_proto + log_arbiter + uart_tx` 串起来，在 `tx_pin` 上自己解码 UART，按线上顺序逐字节断言读应答 8 字节、写帧不应答、数据流帧、应答优先级、帧尾校验失败不写寄存器（第三轮自查新增） | **28 通过 / 0 失败** |
| `tb_sig_audit.v` | 诊断用：只打印四种波形的实际码域范围，不做 pass/fail 判定 | 打印范围 |

合计 **170 项断言通过 / 0 失败**（9 份带判定的 tb）。

### 自查修复记录（2026-10，全模块逐行审查后）

审查前 21 项功能"全部实现"但存在若干真缺陷，修复如下：

| 缺陷 | 位置 | 后果 | 修复 |
| --- | --- | --- | --- |
| 积分项右移量过大 | `rtl\pi_ctrl.v:64-66` | `e32 >>> (ki_shift+9)` = 右移 21 位，而 \|e\| ≤ 16383 ⇒ **正误差恒 0、负误差恒 −1**，积分器实际不工作 | 先 `e32 <<< 9` 再 `>>> ki_s`（`ki_s` 上限 **22**，第二轮复核把 24 收紧） |
| 积分项尺度没还原 | `rtl\pi_ctrl.v:87-88` | 2⁻⁹ 标度的 `integ` 被当作满标度相加，等效增益差 512 倍 | 新增 `i_out = integ >>> 9` 后再与 `prop` 相加 |
| `set_valid` 接错位 | `rtl\light_lock_top.v:222` | 接的是 `ctrl[2]`，而 `ctrl[3:2]` 是模式 ⇒ PI 模式下**永不置位**（死代码），上位机一写还会静默切模式 | 改接 `ctrl[4]` |
| 上位机帧长错 | `host\llctl.py` 读写两处 | 发 6 字节而 RTL 是**定长 8 字节**状态机 ⇒ 写命令隔一帧才生效、读命令永远读回空 | 改成 8 字节帧 |
| 正弦幅度失真 | `rtl\dac_sig_gen.v:180-181` | 用原始 `amp` 且符号扩展取错位（`amp_v[13]` 恒 0）⇒ amp=0x3FFF 只得 [468,15915] | 改用夹取幅度 `amp_norm2`，符号扩展取 `amp_sine_v[14]` |
| 锯齿无视幅度 | `rtl\dac_sig_gen.v:145` | `ramp_span = 0x3FFF − offset`，改 amp 完全无效果 | 改 `ramp_span = amp_norm2` |
| 阶跃模式当电平 | `rtl\dac_sig_gen.v:193` | 把 `amp` 当绝对电平用 ⇒ 默认值下输出是直线 | 改为 `offset + amp_norm` |
| 方差回卷 + 晚一窗口 | `rtl\adc_stats.v` 累加/开窗段 | 方差×16 在 16 位回卷（σ ≥ 64 就错）、`var_q4` 读非阻塞旧值 | 见下方第二轮表格——**第一轮这个修法本身还有错** |
| `ADC_HALF` 静默截断 | `rtl\light_lock_top.v:100` | 端口只有 8 位，写 `0x0100` 变 0 ⇒ ADC 反而跑到 25 MHz | `adc_half` 加宽到 16 位，`HALF_W` 提到 16 |
| `live_min/max` 自引用 | `rtl\light_lock_top.v:333` | `live_max` 自赋值、`live_min` 高 2 位无驱动 | 新增 `stats_min`/`stats_max` 中间线，两路都零扩展 |
| 丢失判定阈值说法 | `rtl\monitor.v:72` | 判据用自增前的旧值 ⇒ 阈值是**连续 2^LOSS_LOG2 拍**（`LOSS_LOG2=8` ⇒ 256 拍 = 5.12 ms），第一轮注释误写成 2^N − 1 | 条件简化并把阈值统一写成 2^N |

第二轮自查（补审第一轮没覆盖的 `step_gen`，并对上面 11 处修复做对抗性复核）新增：

| 缺陷 | 位置 | 后果 | 修复 |
| --- | --- | --- | --- |
| 正弦/三角周期是**平方**关系 | `rtl\step_gen.v` 相位推进 | 一圈 = `256×DIST_PERIOD²`，而同一模块的方波是 `DIST_PERIOD` 拍 ⇒ 默认 `4096` 时正弦一圈约 **16 天**（`DIST_MODE` 默认就是正弦） | 改成每 tick 推进 `2^24/DIST_PERIOD`，与方波、与 `dac_sig_gen` 统一 |
| 正弦多项式**不是奇函数** | `rtl\step_gen.v` 5 级流水多项式 | 含 t²/t⁴ 偶次项 ⇒ 正峰 +2086 / 负峰 −4746（±2048 标度），正负半周严重不对称；峰值还只有 `DIST_AMP/16` | 删掉多项式，正弦/三角改用与 `dac_sig_gen` **共用的查表** `rtl\sin_lut.vh` |
| 扰动幅度口径不一致 | 同上 | 同一个 `DIST_AMP` 在正弦/三角与方波/阶跃之间差 16 倍 | 四种波形峰值一律 = `DIST_AMP`，写 > `0x7FFF` 夹到 `0x7FFF` |
| 缺 testbench | `tb\` | `step_gen` 一个 tb 都没有 ⇒ 上面两个 bug 一直没人发现 | 新增 `tb\tb_step_gen.v`（18 项断言，改回老实现会立刻失败） |
| LED 字节选择没实现 | `rtl\light_lock_top.v:343` | 手册写 `led_status` 由 `CTRL[12:11]` 选 `STATUS` 的字节，代码却是 `\|(\|adc_sample)`，跟 `CTRL` 无关 | 按手册实现字节选择（§6 有选择表） |
| 上位机缺"装订"入口 | `host\llctl.py` | 第一轮新装的 `CTRL[4]` 装订位在上位机库里没有任何 API | 新增 `CTRL_SET_VALID`、`CTRL_MODE_SHIFT`/`MODE_*` 常量与 `bind_pi()` |
| 手册没写积分单位 | `README_REGISTERS.md` §3.5 | `I_CLAMP`/`I_VALUE` 是 **2⁻⁹ 码**单位（默认 ⇒ ±4096 码），且 `I_VALUE` 只回读低 16 位会回卷 | 补单位换算、例子与"别拿 `I_VALUE` 当绝对值"的警告 |
| 统计除法用错参数 | `rtl\adc_stats.v:54-55,80,82,91` | 除法用参数 `LOG2_W=5` 而窗口长度是端口 `log2_n`（默认 12）⇒ 均值大 **128 倍**、方差因柯西–施瓦茨被破坏必然下溢 ⇒ `VAR_Q4` **恒 0xFFFF**（第一轮"饱和防回卷"把错值变成了恒定假值） | 整体重写：除法改用 `log2_n`、本拍样本先并入"下一个和"（窗口正好 2^log2_n 个）、开窗那拍不再丢样本 |
| 读寄存器读回别人的值 | `rtl\uart_proto.v:96-99` | CMD_R 分支只锁存 `latched_addr`，**没有驱动 `reg_addr`** ⇒ 读回的是上一次**写**过的地址的值（地址对、数据错） | CMD_R 分支补 `reg_addr <= frame[2][5:0];` |
| 串口应答字节序反了 | `rtl\log_arbiter.v:86-88` | 移位寄存器**最低字节先发**，而 `resp_data`/快照帧/上位机解析全是高位优先 ⇒ 主机把 dataH/dataL 拼反 | 改成 `tx_byte <= sh[63:56]; sh <= {sh[55:0], 8'h00};`（最高字节先发） |
| `sweep_gen` 比较域是 14 位有符号 | `rtl\sweep_gen.v` 全体 | 码越过中点 `0x2000` 后符号翻转 ⇒ **任何跨中点的向上扫描第一步就"到终点"**（`0x1000→0x3000` 直接跳到 0x3000；默认 `0x0000→0x3FFF` 同理），负步长永远够不到终点 | 整体重写：全程无符号 14 位域、步长取幅值、`cur`/`goal` 双寄存器 + "剩余距离 ≤ 步长就夹到终点" |
| `sweep_gen` 保持拍数 off-by-one | `rtl\sweep_gen.v` 保持计数 | `hold_cnt != hold` 配 0 起始 ⇒ 每步实际保持 `hold+1` 个控制周期 | 判据改 `hold_cnt < hold-1` ⇒ 每步正好 `hold` 拍 |
| `sweep_gen` 连续模式短一步 | `rtl\sweep_gen.v` 转身 | 转身后仍以 `end_code` 为目标 ⇒ 在终点原地抖动，端点码永远不输出 | 转身时先落到端点本身，再交换 `goal` 与方向 |
| `CTRL[10] clr_stats` 是死位 | `rtl\adc_stats.v` | 手册与上位机都承诺"清统计"，但 `adc_stats` 没有 `clr` 端口 ⇒ 最小/最大码从上电起永不归零 | 新增 `clr` 端口并接 `CTRL[10]`，同时清零累加器与 min/max |
| `sweep_gen`/串口读通路没有 testbench | `tb\` | `sweep_gen` 一个 tb 都没有（和 `step_gen` 一样）；全 tb 目录**从不解析回帧** ⇒ 上面几个缺陷都测不出来 | 新增 `tb\tb_sweep_gen.v`（26 项断言）；回帧解析仍是已知缺口 |

第三轮自查（2026-10-14，专审**串口发送链路端到端**，并对全工程做交叉核对；新增 `tb\tb_uart_loop.v` 把整条链路串起来实测）：

| 缺陷 | 位置 | 后果 | 修复 |
| --- | --- | --- | --- |
| 串口**每字节被发两次** | `rtl\log_arbiter.v:87-98` | `uart_tx` 的 `tx_ready`（`state==S_IDLE`）对同一字节**连续两拍为 1**，而仲裁器只判电平 ⇒ `sh`/`cnt` 每字节前进两步，**线上只剩一半字节、内容隔一个取一个**（实测读应答只剩 `C5 10 AB C5`） | 新增 `inflight`：发射条件加 `&& !inflight`，`if (!tx_ready) inflight <= 1'b0;`（等 `uart_tx` 真离开 `S_IDLE` 才算收下） |
| 读应答**无限重发** | `rtl\uart_proto.v:131-133` | 判据 `latched_cmd==CMD_R && latched_rdata==reg_rdata && byte_idx==7` 退化成"byte_idx==7 且上电后读过一次"（`latched_cmd` 只在读分支赋值 ⇒ 读过一次恒为 0x02；`latched_rdata` 每帧 idx6 无条件刷新 ⇒ 到 idx7 必然相等）⇒ `resp_ack` 清零后下一拍立刻重新置位，**以最高优先级无限重发同一帧**；写帧也会被回一帧带旧地址的陈旧应答 | 改成一次性触发：`resp_armed`（收到完整读帧置位、`resp_ack` 时清零），判据改用**本帧**的 `frame[1]==CMD_R` |
| 帧尾两个 `0xC5` **从不校验** | `rtl\uart_proto.v:110-113` | 第 6/7 字节随便是什么都算收帧成功，且写命令在**第 5 字节就落地** ⇒ 丢字节/多插字节会把数据写进**错误的寄存器** | 第 6/7 字节都校验 `0xC5`；写命令改为**延迟提交**（`pend_we/pend_addr/pend_wdata`），任何一处校验不过整帧丢弃 |
| 目标码上溢**漏夹取** | `rtl\light_lock_top.v:195-197` | `sp_sum` 是 17 位有符号，正值只占 bit[15:0]，`sp_sum[15]` **不是**符号位 ⇒ 16384..32767 这一段被漏掉、只截断低 14 位：`SETPOINT=0x3000`+`DIST_AMP=8192` ⇒ 目标码从 12288 **掉到 4096**（应夹到 0x3FFF） | 先判 bit16（负数→0），再用**无符号**比较 `sp_sum[15:0] > 16383` 判上溢 |
| `clk_alive` 在**监视自己的触发器** | `rtl\adc_drv.v:105-121` | 阈值是死数 256 拍：`ADC_HALF≤254` 时它恒 1（AD9248 断线/没供电都报不出来），`ADC_HALF≥255` 时翻转间隔超过 256 拍反而**误报停摆**；STATUS bit5 与 LED 都建在它上面 | 阈值跟着 `half_period` 走（`2*(half+1)+16` 拍内没翻转才算停），并写明它**只能证明内部分频器在动**、证明不了 AD9248 在转换 |
| 手册把"直通"写**反了** | `README_REGISTERS.md:80,188` | 手册说 `CTRL[1]=1` 输出固定 `DAC_CODE`；RTL 是 `wire passthrough = ctrl[1]` → `code_sel = adc_sample`，即**把 PD 的实时噪声原样灌进 AOM 驱动**（固定码其实是 `[3:2]=2`） | 手册两处改写并加 ⚠ |
| 默认值与 RTL 不符 | `rtl\reg_file.v:99-120` | 手册写 `DAC_CODE` 默认 `0x0F0F`、`SIG_MODE` 默认 `6`，RTL 都没有分支（实际复位 0），而 6 也不是合法波形号（合法 0..5） | 给 `6'h02` 补默认值分支；手册把 `SIG_MODE` 默认改成 `0` |
| 参数越界的实际机理写错 | `README_REGISTERS.md:259`、§4.6 | `SIG_PERIOD<16` 时相位加的是 2²⁰、而相位只有 20 位 ⇒ 加法被截断、相位**原地不动**、波形是**恒定直流**（原文写"整圈跳"）；`step_gen` 在 `DIST_PERIOD≤4` 时阶跃恒 0 | 两处口径按实际机理改写 |
| 心跳 LED **看不见** | `rtl\light_lock_top.v:349` | `heartbeat[23]` ⇒ 翻转间隔约 **168 s**，与"不接示波器看死活"的用途对不上 | 改取 `heartbeat[15]` ⇒ 约 **1.31 s** |
| `dbg_marker` 注释与实现不符 | `rtl\dbg_marker.v:5-10`、`README_TESTS.md:104` | 头注释写"送 J3 引脚用示波器量"，实际只在 `ILA_ENABLE` 下接 ILA 探针、顶层无端口无脚；引用的行号 `:412-434` 已过时（实际 `:458-479`） | 注释改写并标明真实接法与两处已知瑕疵（`marker_dac` 是电平、比真实的"ADC 沿→DAC 变"少半拍） |
| 回帧解析**没有 tb** | `tb\` | 全 tb 目录此前**从不解析回帧** ⇒ 上面三个串口缺陷一个都测不出来 | 新增 `tb\tb_uart_loop.v`（28 项断言）：串起 `uart_proto+log_arbiter+uart_tx`，在 `tx_pin` 上自己解码 UART 并逐字节断言 |

第三轮复核**推翻**的旧结论（记下来免得重复怀疑）：
- 第二轮"`sp_sum` 三段钳位正确"的说法**错了** —— 见上表第 4 行，正数 16384..32767 漏夹取。
- 第二轮"`add_sat` 饱和正确"的说法**没有对应代码** —— `rtl\add_sat.v` 在 `rtl\` 里**零实例化**（`pi_ctrl` 用的是普通比较实现饱和，结果等价）；该模块只被编译表引用。
- 波特率的旧说法"位时间 = `baud_div+1` 拍、真实 114,943 bps"**错了** —— `uart_rx` 每位保持 `baud_div` 拍，`baud_div=434` 时是 **115,207 bps**。

审查确认**无问题**的部分（第三轮复核后仍成立）：Q15 正弦查表与象限折返、三角/方波位宽与夹取、`uart_rx` 半位复查与单拍 `rx_vld`、`ctrl_tick` 节拍、`pi_ctrl` 全部定点尺度与抗饱和、`adc_stats` 位宽账、`sweep_gen` 全 14 位无符号比较与终点精度、`monitor` 阈值 2^N、`log_arbiter` 最高字节先发、寄存器地址/读回路与手册一致、XDC 引脚无遗漏。

另有两处**曾被怀疑、复核后推翻**（记录下来免得以后重复怀疑）：
- 子代理报 `sweep_gen` 的 24 位步长只拼出 16 位、符号位恒 0 —— **不成立**：`{sweep_step_hi[7:0], sweep_step_lo}` 正好 24 位，`sweep_step_hi` 本身是 `[15:0]`（`rtl\light_lock_top.v:59`），而 `host\llctl.py` 写步长时 `hi = (step>>16) & 0xFFFF` ⇒ bit23（符号位）在 `sweep_step_hi[7]`，负步长能表达。
- 子代理怀疑 `rtl\reg_file.v` 复位时的 for 循环会被综合成 BRAM 从而不可综合、默认值全变 X —— **不成立**：`build\utilization_post_route.rpt` 实测 `Block RAM Tile 0 / RAMB36 0 / RAMB18 0`、`LUT as Memory 0` ⇒ `mem` 是触发器实现，逐地址装载默认值有效。


**仍需上机/查手册才能定论**（代码里已加注释，未改行为）：
- `rtl\adc_drv.v:71-73` 在 `adc_clk` 沿后仅 1 个 `sys_clk`（20 ns）采数，是否落在 AD9248 数据有效窗口内 —— 需要 AD9248 的 t_DOH/t_HO 或示波器。
- `adc_oeb_n`/`adc_pdn` 恒 0 的极性、`adc_drv.v:53` 的半周期/周期注释口径 —— `hw_params.vh` 自标"未实测"。
- AD9248 模块是 3.3 V 还是 1.8 V 版本、`CLK` 方向 —— 厂家信息缺失。
- `recip_pow2` 的 `busy` 在 K+2 拍才落下（与头注释 K+1 不符，两个调用方都不按 K+1 取商，功能无害）。
- **`constraints\davinci_adc_pi_loop.xdc` 全文没有 `set_input_delay` / `set_output_delay` /
  `create_generated_clock` / `set_clock_groups`** ⇒ ADC 输入、DAC 输出共 30+ 根线**没有任何
  建立/保持分析**（AD9767 的 tSU/tHD 只靠"negedge 更新"那 10 ns 硬撑；`ADC_HALF` 还能写成 0
  ⇒ 25 MHz，xdc 里"5 MHz 余量极大"的说法不再成立）。要补需要板上走线偏斜或 IBIS 数据。
- **全设计没有复位同步器**：`sys_rst_n`（板上按键）直连所有触发器的异步复位端，异步释放时
  各触发器可能不同拍退出复位（`uart_proto` 的 `byte_idx`/`reg_we`、`sweep_gen` 的 `cur`/`goal`/`dir`、
  `reg_file` 的 64 个字）。板载按键的实际抖动同样未知。
- 上送/引脚的两处缺口：`otr_count`/`loss_cnt` **既没有寄存器地址也没有 ILA 探针**（板上取不到
  OTR 计数）；`adc_dac_core` 的 `.data1/.data2` 接的是**同一个码** ⇒ **CH2 实际复读 CH1**、
  `dac2_code` 无人读（与 `rtl\light_lock_top.v:174` 注释"第二路给常量"不符，J2-35..50 已占脚）。

### 两个必踩的工具坑

1. **每次编译前必须删掉旧 sim 目录**。`xvlog` 报错后 `xelab` 会**静默复用上一次成功
   编译的陈旧 snapshot**，让修改看起来"不起作用"。
2. **给 `xvlog`/`xelab`/`xsim` 全部加 `--nolog`**。否则在新目录里会报
   `CRITICAL WARNING: [Common 17-183] Failed to open handle xvlog.log`，
   随后 `xelab` 静默失败、`xsim` 报 snapshot 不存在。
   另外用 PowerShell `>` 重定向的 xsim 输出是 UTF-16LE（读不出来），
   要用 `Out-File -Encoding utf8`。

---

## 6. 与 FPGA 通信

详见 **[README_REGISTERS.md](README_REGISTERS.md)**（寄存器地址全表、位定义、
两个时基公式、以及"**电平位不是脉冲位**"的坑）。

- 串口 **115200 8N1**，`BAUD_DIV = 434`（= 50 MHz / 115200）。
- 写帧：`C5 01 <addr> <dataL> <dataH> 5C`；读帧见寄存器手册。
- 上位机：

```bash
# 全部是 --flag 形式，没有子命令；--port 必给
python host/llctl.py --port COM5 --info                     # 读一组状态量
python host/llctl.py --port COM5 --sine --amp 1024 --period 64 --offset 0x2000   # 【04】正弦输出
python host/llctl.py --port COM5 --stop-sig                 # 停波形
python host/llctl.py --port COM5 --setpoint 8192            # 【12】目标光强码
python host/llctl.py --port COM5 --pi 6 12 --enable         # 【13/16】设 Kp/Ki 并进闭环
python host/llctl.py --port COM5 --disable                  # 退出闭环
python host/llctl.py --port COM5 --step --dist-amp 64 --dist-period 4096   # 【17】阶跃扰动
python host/llctl.py --port COM5 --dist-sine                # 【19】正弦扰动
python host/llctl.py --port COM5 --dist-off                 # 关扰动
python host/llctl.py --port COM5 --sweep --start 0x0000 --end 0x3FFF --step-size 1   # 【07】自动扫描
python host/llctl.py --port COM5 --log --every 64 --count 1000 --out resp.csv       # 【18】记录
python host/llctl.py --port COM5 --clear-flags              # 【15】清标志
python host/llctl.py --port COM5 --read 0x01                # 直接读寄存器
python host/llctl.py --port COM5 --write 0x18 0x2000        # 直接写寄存器
```

⚠️ `SIG_EN[1]`（update）、`DIST_EN[1]`、`CTRL[9]`（清标志）、`SWEEP_CTL[2]`（启动）
都是**电平语义不是脉冲语义**：写完必须再写一次把该位清掉，否则模块每拍都被复位
（这正是早期"正弦输出不动"的根因）。`llctl.py` 的 `pulse_ctrl_bit()` 已封装这一点。

---

## 7. 未完成 / 上机前必须确认

1. **【06】延迟测试目前跑不了**。`dbg_marker.v` 与 `ila_light_lock` 实例都在
   `light_lock_top.v:412-434` 的 `` `ifdef ILA_ENABLE `` 内，**默认构建不含调试核**
   （这是刻意的）。而且：
   - 工程里**没有 `ila_light_lock` 这个 IP**，一旦定义 `ILA_ENABLE` 综合会失败；
   - `marker_adc`/`marker_dac` 只接到了 ILA，**没有引到任何封装引脚**，
     所以 `dbg_marker.v` 注释里说的"各引一根线到示波器"目前做不到。
   要真跑这条测试，得把两个 marker 加成顶层输出端口并补 XDC。
2. **DDS 振幅控制字 13 位 vs 本工程 DAC 14 位**，必然丢一位。丢 LSB（精度
   0.61→1.22 mV）还是丢 MSB（浪费一半量程）**必须先实测再定**，
   切换点是 `hw_params.vh` 的 `DDS_CTRL_DROP_LSB`（默认丢 LSB）。
3. **DDS VCO 输入口特性未查**（等厂家答复）：输入阻抗、是否 DC 耦合、
   允许输入电压。若只吃 0~1 V，DAC 的 ±5 V 必须先衰减。
4. **AD9248 模块版本未确认**：3.3 V 还是 1.8 V IO、CLK 方向。
5. **上机前请先按 `README_TESTS.md` 的步骤逐级验证**，不要直接上闭环。
6. 5 V 排针载流能力未核。

> 曾经列在这里的"`step_gen` 正弦/三角周期与方波口径不一致"已在第二轮自查中**统一**
> （一圈 = `DIST_PERIOD` 个控制周期，默认 `4096` ⇒ 约 82 ms ≈ 12 Hz）。
> 仍无 tb 覆盖的是**串口读回帧的逐字节解析**（现有 tb 只测到 `reg_we`）。
