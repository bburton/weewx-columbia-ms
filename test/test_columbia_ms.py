import sys
import unittest
import columbia_ms

class TestColumbiaMicroServerStation(unittest.TestCase):

    def setUp(self):
        pass
    
    def test_get_data_method_returns_results(self):
        results = ColumbiaMicroServerStation.get_data('file://./latestsampledata_u_us1_fmt.xml')
        assertTrue(results.startswith('<oriondata'), msg='XML content prefix matches')
        
    def test_test(self):
        pass 

if '__name__' == '__main__':
    unittest.main()
