using System;
using System.Threading.Tasks;
using Godot;
using MegaCrit.Sts2.Core.Debug;
using MegaCrit.Sts2.Core.Modding;

namespace STS2MobileIos.Patches;

// Compiled and statically woven before NativeAOT; no runtime patch loader.
public static class OfflinePatches
{
    public static bool InitializeModsPrefix(IModManagerFileIo fileIo,
        ModSettings settings, SemanticVersion gameVersion, ref Task __result)
    {
        // Preserve the fields the normal 'nomods' branch initializes, then skip
        // all scanning, workshop callbacks, dynamic assembly loads and Harmony.
        var type = typeof(ModManager);
        SetRequired(type, "_fileIo", fileIo);
        SetRequired(type, "_settings", settings);
        SetRequired(type, "_gameVersion", gameVersion);
        SetRequired(type, "<State>k__BackingField", ModManagerState.Skipped);
        __result = Task.CompletedTask;
        return false;
    }

    private static void SetRequired(Type type, string field, object value)
    {
        var info = PatchHelper.Field(type, field)
            ?? throw new MissingFieldException(type.FullName, field);
        info.SetValue(null, value);
    }

    public static bool SkipTaskPrefix(ref Task __result)
    {
        __result = Task.CompletedTask;
        return false;
    }

    public static void MainMenuReadyPostfix(Node __instance) => Apply(__instance);
    public static void RefreshButtonsPostfix(Node __instance) => Apply(__instance);

    private static void Apply(Node menu)
    {
        // Verified against this user's v0.111.0 scene; apply again whenever the
        // game refreshes button visibility after a run or profile change.
        var button = menu.GetNodeOrNull<Control>("MainMenuTextButtons/MultiplayerButton");
        if (button != null)
        {
            button.Visible = false;
            button.MouseFilter = Control.MouseFilterEnum.Ignore;
            button.FocusMode = Control.FocusModeEnum.None;
        }
    }
}
