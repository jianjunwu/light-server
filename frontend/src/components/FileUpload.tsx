import { Upload, Switch, message } from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import { useState } from 'react'
import { uploadArtifact } from '@/api/repository'

const { Dragger } = Upload

export default function FileUpload() {
  const [verify, setVerify] = useState(false)

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        Verify signature: <Switch checked={verify} onChange={setVerify} />
      </div>
      <Dragger
        name="file"
        multiple={false}
        accept=".lma"
        customRequest={async ({ file, onSuccess, onError }) => {
          try {
            const res = await uploadArtifact(file as File, verify)
            message.success(`Uploaded ${res.data.name} v${res.data.version}`)
            onSuccess?.(res.data)
          } catch (e: any) {
            message.error(e.message)
            onError?.(e)
          }
        }}
      >
        <p className="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p className="ant-upload-text">Click or drag .lma file to upload</p>
      </Dragger>
    </div>
  )
}
