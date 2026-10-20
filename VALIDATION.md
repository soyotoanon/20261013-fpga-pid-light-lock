# DAC换码时序排障修订 · 2026-10-16

## 已实测现象

COM8串口已联机。旧版固定8192码输出无尖峰；8192/8224慢速切换，用户确认波形清晰。
P-only在未遮光时出现密集尖峰，用户在50ns/格和100ms/格都观察到异常。
随后停止P，保持固定输出。固定输出期间约1秒硬件统计：ADC最小8337、最大8370；
另100次串口采样最小8346、最大8361、平均8354.12。这些结果不能排除其他时间或P运行时的输入异常。
旧版P硬件验收未通过，不把此前仿真通过等同于模拟输出正常。

## 本次修改

旧驱动DAC CLK/WRT同时直接接50MHz sys_clk，数据在下降沿更新；新版改为正沿状态机：
锁存完整数据 -> 20ns后WRT上升 -> 再20ns后CLK上升 -> 返回空闲。
数据在两个锁存阶段保持不变，固定码不重复发无意义的写脉冲，最后一个孤立写请求也会提交到DAC输出级。
PI仍由每个选中ADC有效样本计算，没有改成软件慢循环，也没有加入滤波来隐藏尖峰。
5MS/s请求可逐个完成；驱动理论服务上限12.5MS/s，超过时保留最新请求，不承诺逐样本无丢失。
寄存器0x2F只读值0xD216用于板上确认版本。

依据：[ADI AD9763/9765/9767数据手册，第24页](https://www.analog.com/media/en/technical-documentation/data-sheets/ad9763_9765_9767.pdf)。
手册允许CLK晚于WRT，但要求最小间隔；本版明确分开两个引脚的边沿。
这是一项针对时序疑点的修订，并非已证明旧版所有尖峰都由这一原因导致。

## 验证

- tb_dac_timing_revision通过：4001次5MS/s请求检查，含8191/8192跨中点、多位跳变、双路独立码、最后一次写和过快请求后的最终值。
- tb_sample_revision通过：UART、模式、反馈通道、斜坡及冻结回归。
- tb_pi_revision通过：数值与对象模型回归。
- 本轮共3份相关仿真通过；未把旧的其他模块测试重复计入本轮。
- Vivado BUILD_PASS；WNS=1.759ns，WHS=0.047ns。外部IO仍沿用原false_path约束，内部时序通过不等于板级时序验收。
- bit大小：925212字节，SHA256：9af8f25dd055927ce702ea6cd88e5356706e303ebcaf35eb7f080e5ec37d5f37。
- 新版模拟波形、遮光方向与实际闭环仍待用户示波器观察确认。

备份：`D:\DSproject\workbench\_backup\adc-pi-before-dac-timing-20261016-160126`。

## 本轮实际下载与寄存器确认

已通过已识别的Digilent目标210512180081下载到xc7a35t_0；Vivado输出PROGRAM_DONE=1及PROGRAM_PASS。
随后COM8读0x2F=0xD216，证明板上是本轮修订固件。固定模式读回OUT_CODE=8192。
已恢复P-only：CTRL=1、LOOP_ARM=1、KP_SHIFT=0（Kp=1）、KI_SHIFT=63（I关闭）、
BIAS=8192、OUT_MIN=8128、OUT_MAX=8256、CH1、DIR_POL=1、SP_SLEW=1、LIGHT_TH=0。
用9次读数中位数重设目标8352；配置完成时ADC_CODE=8350、OUT_CODE=8194（寄存器为顺序读取，不是同一时刻快照）。
截至此记录，新版模拟波形仍待用户示波器反馈，不能标为尖峰已解决。

## 2026-10-16 P and integral hardware follow-up
User confirmed D216 no longer fills the scope with spikes; partial shading raises DAC output and release lowers it. After COM9 reconnection, KP_SHIFT=1 readback succeeded and user confirmed roughly half response amplitude.
Integral-only test: KP_SHIFT=15, KI_SHIFT=16, unchanged 5 MHz ADC, bias8192, rails8128/8256. Targets8550 and8166. Upper rail8256 held integralQ9=32768 across two reads separated by300ms; lower rail8128 held integralQ9=-32768 similarly. Falling output samples8250,8218,8187,8150,8128. Clear integral yielded0 and output8192. All sampled outputs within bounds. Host timestamps include UART latency and are not bandwidth/delay measurements. Analog integral waveform was not independently captured.
Restored and verified CTRL1, KP_SHIFT1, KI_SHIFT63, target8352. AOM closed-loop performance remains untested. Evidence: outputs/integral_board_test_20261016.csv and work/integral_board_test.ps1 in current workspace.

## 2026-10-16 19:24 遮光/松开实板诊断

本次未改 RTL、固件、PI 或 DDS 参数。用户确认松开遮光；COM9 连续只读 ADC/ERROR/OUT/STATUS，与独立运行的示波器界面最近读数对照（不是同步延迟测量）。

- 遮光组89条：PD平均0.0239295V，ADC8303.65，ERROR47.93，DAC8215.96，DDS正弦等效Vpp0.8924713V。
- 松开/过渡组11条：PD平均0.0387792V，ADC8330.00，ERROR23.45，DAC8202.82，DDS正弦等效Vpp0.8913265V。后续独立读取ADC8336、ERROR17、DAC8201。
- PI保持CTRL1 ARM1 SETPOINT8352 BIAS8192 KP_SHIFT1 KI_SHIFT63。比例项为对误差绝对值右移一位后恢复符号，与输出变化符合。不同寄存器顺序读取，不应逐行要求精确相等。
- 纠正前次推断：本次输出8216/8201位于8128..8256内部，STATUS2的输出限幅位未置位；当前微弱响应不是输出夹限造成。
- 当前比例项仅支持Kp=2^-shift（最大1），不是任意可编程乘法增益；当前Kp0.5以ADC/DAC码为单位。小误差引起约13..16码DAC变化，现有DAC到DDS局部响应约为毫伏量级，方向正确，不等于已完成闭环验收。
- 图约147..154秒出现独立的RF接近零事件；CSV中原始Vpp也降至0.008V，VRMS约0.00618V，PD基本不变。不是只有紫线换算归零。此时没有本程序的FPGA或DDS参数写入；真实RF中断还是测量链路变化尚未确定，不能归因于PI。
- 原始证据：host/scope_delay_ui/pd_adc_dac_live_20261016.csv；持续示波器CSV位于direct_captures/20261016_191850_795979。

## 2026-10-16 19:32 修改调幅斜率后复测与可视化

用户确认修改的是调幅斜率。保持PI运行，重复目标8352±96后自动恢复8352：DAC8146与8241/8242间，原始波形计算的正弦等效Vpp分别约1.4844/1.4848V与1.5030/1.5033V，幅度差约18.5mV；CH2频率测量50MHz，FFT约50.00008..50.00010MHz，没有检出相应频率变化。证据host/scope_delay_ui/pi_dds_response_after_slope_20261016.json。

随后将KP_SHIFT在线从1改0（Kp0.5改1），读回确认；积分保持关闭63、目标8352、bias8192、输出8128..8256、CTRL1 ARM1，固件仍D216。

界面保留全部原始CSV及原始Vpp数字，下图改为相对启动首个有效值的正弦等效Vpp变化（mV），淡紫色逐点、红色向后1秒滑动均值，显示最近60秒。平滑仅帮助看趋势，不能测延迟。CH2量程0.5V/div用于当前约1.5Vpp载波，NORM采集、100ns/div。

真实遮光已记录（direct_captures/20261016_193115_468239）：2..5秒未遮光，PD均值60.924mV/RF1.492753Vpp；9..11秒遮光，PD26.911mV/RF1.503614Vpp；13..15秒松开，PD59.717mV/RF1.492458Vpp。RF变化约+10.86mV后回落。已目视核实窗口曲线、红线与PD反向变化；464组数据持续采集，无错误。仅确认电子链路响应，不宣称真实AOM闭环或延迟验收。
