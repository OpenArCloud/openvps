import sys
import torch
import json

def getGpuInfo():
    report = {}
    pythonVersion = sys.version_info
    report["Python version"] = str(pythonVersion)

    pytorchVersion = torch.__version__
    report["Pytorch version"] =  str(pytorchVersion)
        
    cudaIsAvailable = torch.cuda.is_available()
    report["CUDA is available"] = str(cudaIsAvailable)

    if not cudaIsAvailable:
        return report
    numDevices = torch.cuda.device_count()
    report["number of devices"] = str(numDevices)
    curDeviceId = torch.cuda.current_device()
    curDeviceName = torch.cuda.get_device_name(curDeviceId)
    report["current device"] = str(curDeviceId) + " (" + str(curDeviceName) + ")"

    return json.dumps(report)

if __name__ == '__main__':
    print("Checking GPU availability...")
    print(getGpuInfo())
