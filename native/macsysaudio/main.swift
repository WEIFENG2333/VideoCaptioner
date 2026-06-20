// macsysaudio — 用 ScreenCaptureKit 捕获本机「系统输出」音频（你电脑正在播放的声音），
// 输出 16kHz / mono / s16le 原始 PCM 到 stdout，供实时字幕父进程读取（与 voxgate 同样的
// 子进程 stdio 模型）。父进程关 stdin（EOF）即停止退出。
//
// 需要「屏幕录制」权限（ScreenCaptureKit 的音频捕获归在该权限下）。未授权时以退出码 2 +
// stderr 标记 "PERMISSION" 退出，父进程据此提示用户去 系统设置 → 隐私与安全性 → 屏幕录制
// 允许后重启。排除本进程自身音频，避免把我们自己的回放也录进去。
//
// 构建：见同目录 build.sh（swiftc 链接 ScreenCaptureKit）。仅 macOS 13+。

import AVFoundation
import CoreMedia
import Foundation
import ScreenCaptureKit

let kSampleRate = 16000
let kChannels = 1

func logErr(_ s: String) {
    FileHandle.standardError.write(Data((s + "\n").utf8))
}

// 退出码约定（父进程解析）：2=无权限/拿不到内容 3=无显示器 4=启动失败 5=运行中出错
func die(_ code: Int32, _ tag: String, _ detail: String = "") {
    logErr(detail.isEmpty ? tag : "\(tag): \(detail)")
    exit(code)
}

final class SystemAudioGrabber: NSObject, SCStreamOutput, SCStreamDelegate, @unchecked Sendable {
    private let out = FileHandle.standardOutput
    private var stream: SCStream?

    func start() async {
        signal(SIGPIPE, SIG_IGN)  // 父进程关读端时别被 SIGPIPE 杀掉，靠写失败/EOF 自行退出

        let content: SCShareableContent
        do {
            // 触发/校验屏幕录制权限；未授权会 throw。
            content = try await SCShareableContent.excludingDesktopWindows(
                false, onScreenWindowsOnly: false)
        } catch {
            die(2, "PERMISSION", error.localizedDescription)
            return
        }
        guard let display = content.displays.first else {
            die(3, "NO_DISPLAY")
            return
        }

        let filter = SCContentFilter(display: display, excludingWindows: [])
        let config = SCStreamConfiguration()
        config.capturesAudio = true
        config.sampleRate = kSampleRate
        config.channelCount = kChannels
        config.excludesCurrentProcessAudio = true
        // 我们只读音频；视频配到最小、低帧率，降低无谓开销（不添加 .screen 输出 → 不交付视频帧）。
        config.width = 2
        config.height = 2
        config.minimumFrameInterval = CMTime(value: 1, timescale: 1)
        config.queueDepth = 6

        let s = SCStream(filter: filter, configuration: config, delegate: self)
        do {
            try s.addStreamOutput(
                self, type: .audio, sampleHandlerQueue: DispatchQueue(label: "vc.sysaudio"))
            try await s.startCapture()
        } catch {
            die(4, "START_ERROR", error.localizedDescription)
            return
        }
        self.stream = s
        logErr("STARTED")  // 父进程据此确认已开始（与 voxgate 的就绪信号类似）
    }

    func stop() async {
        if let s = stream {
            try? await s.stopCapture()
            stream = nil
        }
    }

    // 音频样本回调（在专用队列）：Float32 → Int16，写 stdout。
    func stream(
        _ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
        of type: SCStreamOutputType
    ) {
        guard type == .audio, CMSampleBufferDataIsReady(sampleBuffer) else { return }
        var blockBuffer: CMBlockBuffer?
        var abl = AudioBufferList()
        let status = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            sampleBuffer,
            bufferListSizeNeededOut: nil,
            bufferListOut: &abl,
            bufferListSize: MemoryLayout<AudioBufferList>.size,
            blockBufferAllocator: nil,
            blockBufferMemoryAllocator: nil,
            flags: kCMSampleBufferFlag_AudioBufferList_Assure16ByteAlignment,
            blockBufferOut: &blockBuffer
        )
        guard status == noErr, let raw = abl.mBuffers.mData else { return }
        let byteCount = Int(abl.mBuffers.mDataByteSize)
        let n = byteCount / MemoryLayout<Float32>.size
        if n == 0 { return }
        let floats = raw.bindMemory(to: Float32.self, capacity: n)
        var pcm = [Int16](repeating: 0, count: n)
        for i in 0..<n {
            let v = max(-1.0, min(1.0, floats[i]))
            pcm[i] = Int16(v * 32767.0)
        }
        let data = pcm.withUnsafeBytes { Data($0) }
        do {
            try out.write(contentsOf: data)
        } catch {
            // 父进程已关读端 → 收工退出
            Task { await self.stop(); exit(0) }
        }
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        die(5, "STOPPED_WITH_ERROR", error.localizedDescription)
    }
}

let grabber = SystemAudioGrabber()
Task { await grabber.start() }

// stdin EOF = 父进程要求停止（与 voxgate 一致：关 stdin 即停）。
DispatchQueue.global(qos: .utility).async {
    let stdin = FileHandle.standardInput
    while true {
        let d = stdin.availableData
        if d.isEmpty { break }  // EOF
    }
    Task { await grabber.stop(); exit(0) }
}

// SIGTERM/SIGINT 也干净退出
for sig in [SIGTERM, SIGINT] {
    signal(sig) { _ in exit(0) }
}

RunLoop.main.run()
