#!/usr/bin/swift
import AVFoundation
import Foundation

let timeout = CommandLine.arguments.count > 1 ? Double(CommandLine.arguments[1]) ?? 12.0 : 12.0

func waitForMicPermission() -> Bool {
    switch AVCaptureDevice.authorizationStatus(for: .audio) {
    case .authorized:
        return true
    case .denied, .restricted:
        return false
    case .notDetermined:
        let done = DispatchSemaphore(value: 0)
        var granted = false
        DispatchQueue.main.async {
            AVCaptureDevice.requestAccess(for: .audio) { ok in
                granted = ok
                done.signal()
            }
        }
        let deadline = Date(timeIntervalSinceNow: 30)
        while done.wait(timeout: .now() + 0.05) == .timedOut {
            RunLoop.main.run(mode: .default, before: Date(timeIntervalSinceNow: 0.05))
            if Date() > deadline {
                return false
            }
        }
        return granted
    @unknown default:
        return false
    }
}

guard waitForMicPermission() else {
    fputs("ERROR: Microphone permission denied\n", stderr)
    exit(2)
}

let tempURL = FileManager.default.temporaryDirectory
    .appendingPathComponent("jarvis-\(ProcessInfo.processInfo.processIdentifier).wav")

let settings: [String: Any] = [
    AVFormatIDKey: Int(kAudioFormatLinearPCM),
    AVSampleRateKey: 16_000,
    AVNumberOfChannelsKey: 1,
    AVLinearPCMBitDepthKey: 16,
    AVLinearPCMIsFloatKey: false,
    AVLinearPCMIsBigEndianKey: false,
]

let recorder: AVAudioRecorder
do {
    recorder = try AVAudioRecorder(url: tempURL, settings: settings)
    recorder.prepareToRecord()
} catch {
    fputs("ERROR: Recorder init failed — \(error.localizedDescription)\n", stderr)
    exit(3)
}

guard recorder.record() else {
    fputs("ERROR: Could not start recording\n", stderr)
    exit(4)
}

Thread.sleep(forTimeInterval: timeout)
recorder.stop()

let fileSize = (try? FileManager.default.attributesOfItem(atPath: tempURL.path)[.size] as? Int) ?? 0
if fileSize < 1024 {
    try? FileManager.default.removeItem(at: tempURL)
    exit(0)
}

print(tempURL.path)
