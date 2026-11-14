using BepInEx;

namespace HookProfiler
{
    [BepInPlugin("hookprofiler", "HookProfiler", "1.0.0")]
    [BepInDependency("CasualtiesMP", BepInDependency.DependencyFlags.SoftDependency)]
    public class Plugin : BaseUnityPlugin
    {
        void Awake()
        {
            Logger.LogInfo("HookProfiler loaded; idle until Control.Install is called through the link");
        }
    }
}
