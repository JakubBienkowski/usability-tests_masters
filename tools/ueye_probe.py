import ctypes
import os
import time


UEYE_CANDIDATE_BINS = [
    r"C:\Program Files\IDS\uEye\USB driver package",
    r"C:\Program Files\IDS\uEye\Develop\Bin",
    r"C:\Program Files\IDS\ids_peak\ueye\develop\bin",
]


def load_api():
    for candidate in UEYE_CANDIDATE_BINS:
        dll = os.path.join(candidate, "ueye_api_64.dll")
        if not os.path.exists(dll):
            continue
        print(f"Loading uEye API: {dll}")
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(candidate)
        return ctypes.WinDLL(dll)
    raise FileNotFoundError("ueye_api_64.dll was not found in known IDS locations")


ERROR_NAMES = {
    0: "IS_SUCCESS",
    1: "IS_INVALID_CAMERA_HANDLE",
    3: "IS_CANT_OPEN_DEVICE",
    120: "IS_ALL_DEVICES_BUSY",
    122: "IS_TIMED_OUT",
    155: "IS_NOT_SUPPORTED",
    180: "IS_INVALID_CAMERA_TYPE",
    184: "IS_STARTER_FW_UPLOAD_NEEDED",
}


def print_last_error(api, h_cam, label):
    try:
        err = ctypes.c_int(0)
        msg = ctypes.c_char_p()
        ret = api.is_GetError(h_cam, ctypes.byref(err), ctypes.byref(msg))
        text = msg.value.decode(errors="replace") if msg.value else ""
        err_name = ERROR_NAMES.get(err.value, "UNKNOWN")
        print(f"[{label}] is_GetError ret: {ret}, err: {err.value} ({err_name}), text: {text}")
    except AttributeError:
        print(f"[{label}] is_GetError is not exported")
    except Exception as exc:
        print(f"[{label}] is_GetError failed: {exc}")


def init_and_close(api, initial_handle, label):
    h_cam = ctypes.c_int(initial_handle)
    print(f"\n[{label}] is_InitCamera input handle: 0x{initial_handle:x} ({initial_handle})")
    ret = api.is_InitCamera(ctypes.byref(h_cam), None)
    ret_name = ERROR_NAMES.get(ret, "UNKNOWN")
    print(f"[{label}] is_InitCamera ret: {ret} ({ret_name}), output handle: {h_cam.value}")
    if ret != 0:
        print_last_error(api, h_cam, label)
    if ret == 0:
        exit_ret = api.is_ExitCamera(h_cam)
        print(f"[{label}] is_ExitCamera ret: {exit_ret}")
    return ret


class UEYE_CAMERA_INFO(ctypes.Structure):
    _fields_ = [
        ("dwCameraID", ctypes.c_uint32),
        ("dwDeviceID", ctypes.c_uint32),
        ("dwSensorID", ctypes.c_uint32),
        ("dwInUse", ctypes.c_uint32),
        ("SerNo", ctypes.c_char * 16),
        ("Model", ctypes.c_char * 16),
        ("dwStatus", ctypes.c_uint32),
        ("dwReserved", ctypes.c_uint32 * 2),
        ("FullModelName", ctypes.c_char * 32),
        ("dwReserved2", ctypes.c_uint32 * 5),
    ]


def print_camera_list(api, count):
    if count <= 0:
        return

    class UEYE_CAMERA_LIST(ctypes.Structure):
        _fields_ = [
            ("dwCount", ctypes.c_uint32),
            ("uci", UEYE_CAMERA_INFO * count),
        ]

    camera_list = UEYE_CAMERA_LIST()
    camera_list.dwCount = count
    ret = api.is_GetCameraList(ctypes.byref(camera_list))
    print(f"is_GetCameraList ret: {ret}, count field: {camera_list.dwCount}")

    for index in range(camera_list.dwCount):
        item = camera_list.uci[index]
        serial = item.SerNo.split(b"\0", 1)[0].decode(errors="replace")
        model = item.Model.split(b"\0", 1)[0].decode(errors="replace")
        full_model = item.FullModelName.split(b"\0", 1)[0].decode(errors="replace")
        print(
            "  camera[{idx}]: camera_id={cid}, device_id={did}, sensor_id={sid}, "
            "in_use={in_use}, status=0x{status:08x}, serial={serial}, "
            "model={model}, full_model={full_model}".format(
                idx=index,
                cid=item.dwCameraID,
                did=item.dwDeviceID,
                sid=item.dwSensorID,
                in_use=item.dwInUse,
                status=item.dwStatus,
                serial=serial,
                model=model,
                full_model=full_model,
            )
        )


def main():
    api = load_api()

    try:
        dll_version = api.is_GetDLLVersion()
        print(f"uEye DLL version raw: {dll_version}")
    except AttributeError:
        print("is_GetDLLVersion is not exported")

    camera_count = ctypes.c_uint(0)
    try:
        ret = api.is_GetNumberOfCameras(ctypes.byref(camera_count))
        print(f"is_GetNumberOfCameras ret: {ret}, count: {camera_count.value}")
        print_camera_list(api, camera_count.value)
    except AttributeError:
        print("is_GetNumberOfCameras is not exported")

    # Known flags used by IDS uEye examples and legacy cold-start flows.
    is_use_device_id = 0x8000
    is_allow_starter_fw_upload = 0x10000
    is_allow_fw_upload = is_allow_starter_fw_upload

    cases = [
        (0, "auto"),
        (1, "camera-id-1-plain"),
        (1 | is_use_device_id, "device-id-1"),
        (1 | is_use_device_id | is_allow_fw_upload, "device-id-1-fw-upload"),
        (10, "device-id-10-plain"),
        (10 | is_use_device_id, "device-id-10"),
        (10 | is_use_device_id | is_allow_fw_upload, "device-id-10-fw-upload"),
    ]

    results = []
    for handle, label in cases:
        results.append((label, init_and_close(api, handle, label)))
        time.sleep(2)

    print("\nSummary:")
    for label, ret in results:
        print(f"  {label}: {ret}")


if __name__ == "__main__":
    main()
