# Minimal `winsdk` typing subset

These local stubs cover only the WinRT APIs imported by
`catlabel.transport.bluetooth.adapters.windows_winrt`:

- `winsdk.windows.devices.bluetooth`
- `winsdk.windows.devices.bluetooth.rfcomm`
- `winsdk.windows.devices.enumeration`
- `winsdk.windows.networking`
- `winsdk.windows.networking.sockets`
- `winsdk.windows.storage.streams`

The source is the `winsdk` 1.0.0b10 CPython 3.11 Windows x64 wheel with SHA-256
`f12e25bbf0a658270203615677520b8170edf500fba11e0f80359c5dbf090676`. This is a
small, manually maintained structural subset of the wheel's type declarations,
not a copy of the complete SDK stubs. The wheel's MIT license is included in
`LICENSE`.

Signatures and the included enum values were checked against the wheel's
namespace `.pyi` files. WinRT async operations are represented as
`collections.abc.Awaitable` of their awaited result, and WinRT `Guid` is
represented as `uuid.UUID` where used by catlabel.

The local fake-SDK tests check the adapter's call shape only; native Windows
behavior remains unverified. Recheck this subset against the pinned wheel
whenever the `winsdk` dependency version or wheel changes.
