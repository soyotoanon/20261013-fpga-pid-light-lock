import unittest
from llctl import LightLock

class FakeLink(LightLock):
    def __init__(self):
        self.writes=[]
        self.armed=0
    def write_reg(self,addr,value,settle=0):
        self.writes.append((addr,value))
        if addr==0x2e:self.armed=int(value==0xa501)
        if addr in (0x20,0x2d):self.armed=0
    def read_reg(self,addr,settle=0):
        return (self.armed if addr==0x2e else 0),b''

class HostTests(unittest.TestCase):
    def test_refuses_enable_without_arm(self):
        link=FakeLink()
        with self.assertRaises(RuntimeError):link.enable_pi()
        self.assertEqual(link.writes,[])
    def test_arm_then_enable_preserves_bias(self):
        link=FakeLink();link.arm_pi();link.enable_pi()
        self.assertEqual(link.writes,[(0x2e,0xa501),(0,1)])
    def test_parameter_transaction_disarms_first(self):
        link=FakeLink();link.arm_pi();link.writes=[];link.set_pi(6,63)
        self.assertEqual(link.writes[0],(0x2e,0))
        self.assertEqual(link.armed,0)
    def test_invalid_config_writes_nothing(self):
        link=FakeLink()
        for args in [dict(out_min=9000,out_max=8000),dict(i_clamp=0x80000000),dict(dir_pol=2)]:
            with self.assertRaises(ValueError):link.set_pi(6,12,**args)
        self.assertEqual(link.writes,[])
    def test_target_validation_and_online_update(self):
        link=FakeLink();link.arm_pi();link.writes=[]
        for code in [-1,16384]:
            with self.assertRaises(ValueError):link.set_setpoint(code)
        link.set_setpoint(12345)
        self.assertEqual(link.writes,[(0x18,12345)])
        self.assertEqual(link.armed,1)
    def test_switching_channel_disarms(self):
        link=FakeLink();link.arm_pi();link.select_feedback(2)
        self.assertEqual(link.writes[-1],(0x2d,1));self.assertEqual(link.armed,0)
    def test_disable_disarms(self):
        link=FakeLink();link.arm_pi();link.disable()
        self.assertEqual(link.writes[-2:],[(0,0),(0x2e,0)])

if __name__=='__main__':unittest.main()
