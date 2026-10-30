using System;
using System.IO;
using System.Diagnostics;
using System.Windows.Forms;
class ESA {
 [STAThread] static int Main(string[] args) {
  string root=AppDomain.CurrentDomain.BaseDirectory;
  string registry=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"ESA","workspaces.json");
  string selected=null;
  if(args.Length==0 && !File.Exists(registry)) {
   var choice=MessageBox.Show("欢迎使用 ESA。\n\n继续已有工作区请选择‘是’；新建个人工作区请选择‘否’。\n已有工作区应包含 workspace.json 和 app.sqlite3。", "ESA · 选择工作区",MessageBoxButtons.YesNoCancel,MessageBoxIcon.Question);
   if(choice==DialogResult.Cancel)return 0;
   if(choice==DialogResult.Yes) {using(var dialog=new FolderBrowserDialog()){dialog.Description="选择已有ESA工作区（包含workspace.json和app.sqlite3）";if(dialog.ShowDialog()!=DialogResult.OK)return 0;selected=dialog.SelectedPath;if(!File.Exists(Path.Combine(selected,"workspace.json"))||!File.Exists(Path.Combine(selected,"app.sqlite3"))){MessageBox.Show("这不是已有的ESA工作区。资料没有改变。", "ESA");return 1;}}}
   else selected=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"ESA","workspaces","default");
  }
  try {
   var info=new ProcessStartInfo(Path.Combine(root,"runtime","python.exe"));
   info.WorkingDirectory=root; info.UseShellExecute=false;info.CreateNoWindow=true;
   info.RedirectStandardError=true;info.RedirectStandardOutput=true;
   info.Arguments="-B -X utf8 -m app.launcher open";
   if(selected!=null)info.Arguments+=" --data-dir "+Quote(selected);
   foreach(string arg in args)info.Arguments+=" "+Quote(arg);
   using(var process=Process.Start(info)) {string output=process.StandardOutput.ReadToEnd();string error=process.StandardError.ReadToEnd();process.WaitForExit();if(process.ExitCode!=0){MessageBox.Show("启动没有完成。\n\n"+error,"ESA · 启动问题",MessageBoxButtons.OK,MessageBoxIcon.Warning);return process.ExitCode;}}
   return 0;
  } catch(Exception e) {MessageBox.Show("无法启动内置运行时，请完整解压发行目录。\n\n"+e.Message,"ESA");return 1;}
 }
 static string Quote(string value) {
  var result=new System.Text.StringBuilder(); result.Append('"'); int slashes=0;
  foreach(char c in value) {
   if(c=='\\') {slashes++;continue;}
   if(c=='"') {result.Append('\\',slashes*2+1);result.Append(c);}
   else {result.Append('\\',slashes);result.Append(c);}
   slashes=0;
  }
  result.Append('\\',slashes*2);result.Append('"');return result.ToString();
 }
}
