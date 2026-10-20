# UART 寄存器表（2026-10-15）

115200、8N1。写帧：`C5 01 addr data_lo data_hi 5C C5 C5`；读帧：`C5 02 addr 00 00 5C C5 C5`。地址为 6 位，数据为 16 位，小端。

| 地址 | 名称 | 含义 / 默认值 |
|---|---|---|
| 00 | CTRL | 默认0；bit0启用PI；bit1双路直通；bits3:2模式；bit4装载u0并清I；bit8清I；bit9清标志；bit10清统计；bits12:11 LED状态选择 |
| 01 | STATUS | 只读；bit0光丢失、bit1历史OTR、bit2输出到限、bit3积分到限、bit4冻结、bit5内部分频时钟停摆、bit6扫描完成 |
| 02 | DAC_CODE | 固定输出码，默认0x0F0F |
| 03 | ADC_CODE | 只读，当前选中通道的归一化码 |
| 04 | ERROR | 只读，有符号16位，PI最后一次计算的误差 |
| 05 | OUT_CODE | 只读，实际DAC1输出码 |
| 06..09 | MEAN, VAR_Q4, MIN, MAX | 只读统计；平均/方差按样本窗口；min/max自清统计起累计 |
| 0A..0F | SWEEP_START, END, STEP_LO, STEP_HI, HOLD, CTL | 扫描参数；CTL bit0启用、bit1连续、bit2启动 |
| 10 | CTRL_HALF | 默认499；测试发生器/日志周期为2*(值+1)/50MHz；不控制PI |
| 11 | ADC_HALF | 默认4；每路采样率50MHz/[2*(值+1)]；运行参数更改后须重核积分增益 |
| 12..17 | SIG_EN, MODE, FIXED, AMP, OFF, PERIOD | 测试波形；EN bit0启用、bit1更新；MODE 0固定/1方波/2阶跃/3锯齿/4三角/5正弦 |
| 18 | SETPOINT | 目标归一化ADC码，默认8192，0..16383 |
| 19 | BIAS_CODE | u0，默认8192，未标定占位值 |
| 1A | KP_SHIFT | 默认6；0..14为2^-shift，15..31关闭P |
| 1B | KI_SHIFT | 默认12；0..22为每样本2^-shift，23..63关闭I |
| 1C / 1D | I_CLAMP_LO / HI | Q9积分绝对值上限，默认0x00200000（4096码）；0关闭积分；bit31置位时RTL按0x7FFFFFFF处理 |
| 1E / 1F | OUT_MIN / MAX | 默认0/16383；对PI有效，直通/固定码/测试波形按各自输出值运行 |
| 20 | DIR_POL | bit0：1正作用、0反作用；写此寄存器取消LOOP_ARM |
| 21 | LIGHT_TH | 默认16；归一化暗场阈值，0禁用；须按实际暗场标定 |
| 22 | STATS_LOG2 | 默认12；每窗口2^N个有效ADC样本 |
| 23..26 | DIST_EN, MODE, AMP, PERIOD | 目标扰动；叠加后经过限幅和目标斜坡；MODE 0关/1阶跃/2方波/3正弦/4三角 |
| 27 / 28 | LOG_EVERY / STREAM_EN | 日志抽取，仍按CTRL_HALF节拍 |
| 29 | BAUD_DIV | 默认434 |
| 2A / 2B | I_VALUE_LO / HI | 只读Q9积分；运行中两次读取可能跨样本，需精确快照时先停止PI再读 |
| 2C | SP_SLEW | 新增；默认1；每个样本最大目标变化码数；0按1，超16383夹到16383 |
| 2D | FEEDBACK_CH | 新增；0=CH1，1=CH2；默认0；写入取消LOOP_ARM |
| 2E | LOOP_ARM | 新增；上电0；写0xA501解锁，其他值取消；读回0/1 |
| 2F..3F | 保留 | 读回0 |

模式 bits3:2：0 PI、1测试波形、2固定码、3扫描；CTRL[1] 直通优先。例：CTRL=2直通、CTRL=8固定码、CTRL=1请求PI；PI另需LOOP_ARM=1。

SETPOINT、BIAS_CODE、DAC_CODE、OUT_MIN/MAX、SP_SLEW 的非法高值在写入时饱和，不截位。KP/KI_SHIFT 分别饱和到31/63。DIR_POL/FEEDBACK_CH只保留bit0。其他历史测试寄存器沿用原位宽定义。

主机 `set_pi()` 在写多个寄存器前取消LOOP_ARM，防止积分高低字或输出上下限的中间状态进入闭环；完成后须显式重新解锁。手工多寄存器更新也应先取消LOOP_ARM。在线改 SETPOINT/SP_SLEW 无需停环。CTRL的清除/装载位仍是电平，不会自动清零。OTR源为ADC粘滞位，清监视标志后可能再次报告历史OTR，完全清除需复位。
